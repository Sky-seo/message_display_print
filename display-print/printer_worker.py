#!/usr/bin/env python3
import argparse
import json
import os
import time
from datetime import datetime
from urllib import error, request

try:
  from escpos.printer import Usb
except Exception:
  Usb = None

try:
  from PIL import Image, ImageDraw, ImageFont
except Exception:
  Image = None
  ImageDraw = None
  ImageFont = None


printer_instance = None
PRINT_WIDTH_PX = 350


def load_json(path, default):
  if not os.path.exists(path):
    return default
  with open(path, "r", encoding="utf-8") as f:
    raw = f.read().strip()
  if not raw:
    return default
  try:
    return json.loads(raw)
  except json.JSONDecodeError:
    return default


def save_json(path, data):
  with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")


def parse_hex_or_int(value):
  value = str(value).strip().lower()
  if value.startswith("0x"):
    return int(value, 16)
  return int(value, 10)


def fetch_entries_from_url(source_url, source_timeout, source_token):
  headers = {"Accept": "application/json"}
  if source_token:
    headers["Authorization"] = f"Bearer {source_token}"

  req = request.Request(source_url, headers=headers, method="GET")
  with request.urlopen(req, timeout=source_timeout) as resp:
    body = resp.read().decode("utf-8")

  data = json.loads(body)
  if not isinstance(data, list):
    raise ValueError("Source URL did not return a JSON array")
  return data


def get_entries(args):
  if args.source_url:
    return fetch_entries_from_url(
      source_url=args.source_url,
      source_timeout=args.source_timeout,
      source_token=args.source_token,
    )
  data = load_json(args.log_path, [])
  return data if isinstance(data, list) else []


def format_print_text(entry):
  created_at = entry.get("createdAt", "")
  value = entry.get("value", "")

  try:
    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    created_display = dt.strftime("%Y-%m-%d %H:%M:%S")
  except ValueError:
    created_display = created_at

  lines = [
    "Falling Text Input",
    "------------------",
    f"Time: {created_display}",
    "",
    value,
    "",
    "",
    "",
    "",
    "",
    "",
    "",
    "",
  ]
  return "\n".join(lines)


def find_korean_font_path():
  candidates = [
    "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
    "/Library/Fonts/AppleGothic.ttf",
  ]
  for path in candidates:
    if os.path.exists(path):
      return path
  return None


def wrap_line_to_width(draw, line, font, max_width):
  if not line:
    return [""]

  wrapped = []
  current = ""
  for ch in line:
    candidate = current + ch
    bbox = draw.textbbox((0, 0), candidate, font=font)
    candidate_width = bbox[2] - bbox[0]
    if candidate_width <= max_width or not current:
      current = candidate
      continue
    wrapped.append(current)
    current = ch

  if current:
    wrapped.append(current)

  return wrapped


def render_entry_image(entry, width=PRINT_WIDTH_PX, margin=24, line_gap=10, font_size=28):
  if Image is None:
    raise RuntimeError("Pillow is not installed. Run: pip3 install pillow")

  text = format_print_text(entry)
  font_path = find_korean_font_path()
  font = ImageFont.truetype(font_path, font_size) if font_path else ImageFont.load_default()

  dummy = Image.new("L", (width, 10), 255)
  draw = ImageDraw.Draw(dummy)

  lines = text.split("\n")
  max_text_width = max(1, width - margin * 2)
  wrapped_lines = []
  for line in lines:
    wrapped_lines.extend(wrap_line_to_width(draw, line, font, max_text_width))

  heights = []
  for line in wrapped_lines:
    bbox = draw.textbbox((0, 0), line if line else " ", font=font)
    heights.append(bbox[3] - bbox[1])

  content_h = sum(heights) + max(0, len(wrapped_lines) - 1) * line_gap
  height = margin * 2 + content_h

  img = Image.new("L", (width, height), 255)
  draw = ImageDraw.Draw(img)

  y = margin
  for i, line in enumerate(wrapped_lines):
    draw.text((margin, y), line, font=font, fill=0)
    y += heights[i] + line_gap

  return img


def pil_to_escpos_raster_bytes(img):
  bw = img.convert("1")
  width, height = bw.size
  width_bytes = (width + 7) // 8
  pixels = bw.load()

  data = bytearray()
  for y in range(height):
    for xb in range(width_bytes):
      byte = 0
      for bit in range(8):
        x = xb * 8 + bit
        if x >= width:
          continue
        if pixels[x, y] == 0:
          byte |= (0x80 >> bit)
      data.append(byte)

  xL = width_bytes & 0xFF
  xH = (width_bytes >> 8) & 0xFF
  yL = height & 0xFF
  yH = (height >> 8) & 0xFF

  header = bytearray()
  header += b"\x1b\x40"      # init
  header += b"\x1b\x33\x00"  # line spacing 0
  header += b"\x1d\x76\x30\x00"
  header += bytes([xL, xH, yL, yH])

  return bytes(header + data)


def get_printer(vendor_id, product_id, interface, in_ep, out_ep, timeout_ms, usb_profile):
  global printer_instance

  if Usb is None:
    raise RuntimeError("python-escpos is not installed. Run: pip3 install python-escpos")

  if printer_instance is None:
    print("Initializing USB ESC/POS printer...")
    printer_instance = Usb(
      vendor_id,
      product_id,
      interface=interface,
      in_ep=in_ep,
      out_ep=out_ep,
      timeout=timeout_ms,
      profile=usb_profile,
    )
    for codepage in ("KOR", "CP949", "EUC-KR", "USA"):
      try:
        printer_instance.charcode(codepage)
        break
      except Exception:
        continue

  return printer_instance


def print_entry_usb(entry, vendor_id, product_id, interface, in_ep, out_ep, timeout_ms, usb_profile):
  p = get_printer(vendor_id, product_id, interface, in_ep, out_ep, timeout_ms, usb_profile)
  img = render_entry_image(entry)
  raster = pil_to_escpos_raster_bytes(img)
  p._raw(raster)
  p._raw(b"\n")
  p.cut()


def main():
  global printer_instance

  parser = argparse.ArgumentParser(description="USB receipt printer worker for display-print.")
  parser.add_argument("--log-path", default="log.json", help="Local source log JSON file path.")
  parser.add_argument("--source-url", default=None, help="Remote JSON array API URL.")
  parser.add_argument("--source-timeout", type=float, default=5.0, help="Remote source timeout seconds.")
  parser.add_argument("--source-token", default=None, help="Optional bearer token for source URL.")
  parser.add_argument("--state-path", default="printed_ids.json", help="Printed-id tracking file path.")
  parser.add_argument("--interval", type=float, default=1.0, help="Polling interval seconds.")
  parser.add_argument("--usb-vendor-id", default="0x0485", help="USB vendor id.")
  parser.add_argument("--usb-product-id", default="0x5741", help="USB product id.")
  parser.add_argument("--usb-interface", type=int, default=0, help="USB interface number.")
  parser.add_argument("--usb-in-ep", default="0x81", help="USB IN endpoint.")
  parser.add_argument("--usb-out-ep", default="0x03", help="USB OUT endpoint.")
  parser.add_argument("--usb-profile", default="TM-T88III", help="python-escpos profile name.")
  parser.add_argument("--usb-timeout-ms", type=int, default=3000, help="USB write timeout in ms.")
  parser.add_argument("--dry-run", action="store_true", help="Print nothing; log only.")
  args = parser.parse_args()

  usb_vendor_id = parse_hex_or_int(args.usb_vendor_id)
  usb_product_id = parse_hex_or_int(args.usb_product_id)
  usb_in_ep = parse_hex_or_int(args.usb_in_ep)
  usb_out_ep = parse_hex_or_int(args.usb_out_ep)

  printed_ids = set(load_json(args.state_path, []))
  failed_ids = set()

  if not os.path.exists(args.state_path):
    save_json(args.state_path, sorted(printed_ids))

  print("Printer worker started.")
  if args.source_url:
    print(f"source     : {args.source_url}")
  else:
    print(f"log path   : {args.log_path}")
  print(f"state path : {args.state_path}")
  print(f"usb id     : 0x{usb_vendor_id:04x}:0x{usb_product_id:04x}")
  print(f"usb iface  : {args.usb_interface}")
  print(f"usb ep     : in=0x{usb_in_ep:02x} out=0x{usb_out_ep:02x}")
  print(f"interval   : {args.interval}s")
  print(f"dry run    : {args.dry_run}")

  while True:
    try:
      entries = get_entries(args)
    except error.HTTPError as e:
      print(f"Source HTTP error: {e.code} {e.reason}")
      time.sleep(args.interval)
      continue
    except error.URLError as e:
      print(f"Source URL error: {e.reason}")
      time.sleep(args.interval)
      continue
    except Exception as e:
      print(f"Source read error: {e}")
      time.sleep(args.interval)
      continue

    has_new = False

    for entry in entries:
      if not isinstance(entry, dict):
        continue

      entry_id = entry.get("id")
      value = entry.get("value")
      if not entry_id or not isinstance(value, str) or not value.strip():
        continue
      if entry_id in printed_ids or entry_id in failed_ids:
        continue

      try:
        if args.dry_run:
          print(f"[DRY RUN] Would print id={entry_id} value={value!r}")
        else:
          print_entry_usb(
            entry=entry,
            vendor_id=usb_vendor_id,
            product_id=usb_product_id,
            interface=args.usb_interface,
            in_ep=usb_in_ep,
            out_ep=usb_out_ep,
            timeout_ms=args.usb_timeout_ms,
            usb_profile=args.usb_profile,
          )
          print(f"Printed id={entry_id}")

        printed_ids.add(entry_id)
        has_new = True

      except AssertionError as e:
        print(f"Assertion error for id={entry_id}: {str(e).strip() or repr(e)}")
        failed_ids.add(entry_id)

      except Exception as e:
        print(f"Unexpected error for id={entry_id}: {str(e).strip() or repr(e)}")
        failed_ids.add(entry_id)
        printer_instance = None

    if has_new:
      save_json(args.state_path, sorted(printed_ids))

    time.sleep(args.interval)


if __name__ == "__main__":
  main()
