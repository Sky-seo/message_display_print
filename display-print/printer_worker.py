#!/usr/bin/env python3
import argparse
import json
import os
import socket
import subprocess
import tempfile
import time
from datetime import datetime

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


def load_json(path, default):
  if not os.path.exists(path):
    return default
  with open(path, "r", encoding="utf-8") as f:
    raw = f.read().strip()
  if not raw:
    return default
  try:
    data = json.loads(raw)
  except json.JSONDecodeError:
    return default
  return data


def save_json(path, data):
  with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
    f.write("\n")


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
    "------------------",
  ]
  return "\n".join(lines)


def build_escpos_payload(entry):
  text = format_print_text(entry)
  payload = bytearray()
  payload += b"\x1b\x40"  # Initialize
  payload += b"\x1b\x61\x01"  # Align center
  payload += "Falling Text\n".encode("utf-8", errors="ignore")
  payload += b"\x1b\x61\x00"  # Align left
  payload += (text + "\n\n").encode("utf-8", errors="ignore")
  payload += b"\x1d\x56\x00"  # Full cut
  return bytes(payload)


def get_printer(vendor_id, product_id, interface, in_ep, out_ep, timeout_ms):
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
    )
    for codepage in ("KOR", "CP949", "EUC-KR", "USA"):
      try:
        printer_instance.charcode(codepage)
        break
      except Exception:
        continue
  return printer_instance


def print_entry(text, printer_name=None):
  with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tf:
    tf.write(text)
    temp_path = tf.name

  try:
    cmd = ["lp"]
    if printer_name:
      cmd += ["-d", printer_name]
    cmd.append(temp_path)
    subprocess.run(cmd, check=True, capture_output=True, text=True)
  finally:
    if os.path.exists(temp_path):
      os.remove(temp_path)


def print_entry_pos(entry, host, port, timeout):
  payload = build_escpos_payload(entry)
  with socket.create_connection((host, port), timeout=timeout) as sock:
    sock.sendall(payload)


def parse_hex_or_int(value):
  value = str(value).strip().lower()
  if value.startswith("0x"):
    return int(value, 16)
  return int(value, 10)


def print_entry_usb_escpos(entry, vendor_id, product_id, interface, in_ep, out_ep, timeout_ms):
  p = get_printer(
    vendor_id=vendor_id,
    product_id=product_id,
    interface=interface,
    in_ep=in_ep,
    out_ep=out_ep,
    timeout_ms=timeout_ms,
  )
  p.set(align="center")
  p.text("Falling Text Input\n")
  p.set(align="left")
  p.text(format_print_text(entry))
  p.text("\n\n")
  p.cut()


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


def print_entry_usb_image(entry, vendor_id, product_id, interface, in_ep, out_ep, timeout_ms):
  if Image is None:
    raise RuntimeError("Pillow is not installed. Run: pip3 install pillow")

  p = get_printer(
    vendor_id=vendor_id,
    product_id=product_id,
    interface=interface,
    in_ep=in_ep,
    out_ep=out_ep,
    timeout_ms=timeout_ms,
  )

  text = format_print_text(entry)
  font_path = find_korean_font_path()
  font = ImageFont.truetype(font_path, 28) if font_path else ImageFont.load_default()

  width = 576
  margin = 24
  line_gap = 10
  dummy = Image.new("L", (width, 10), 255)
  draw = ImageDraw.Draw(dummy)

  lines = text.split("\n")
  line_heights = []
  for line in lines:
    bbox = draw.textbbox((0, 0), line if line else " ", font=font)
    line_heights.append((bbox[3] - bbox[1]))

  content_h = sum(line_heights) + max(0, len(lines) - 1) * line_gap
  height = margin * 2 + content_h
  img = Image.new("L", (width, height), 255)
  draw = ImageDraw.Draw(img)

  y = margin
  for i, line in enumerate(lines):
    draw.text((margin, y), line, font=font, fill=0)
    y += line_heights[i] + line_gap

  with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
    image_path = tf.name
  try:
    img.save(image_path, format="PNG")
    p.image(image_path)
    p.text("\n")
    p.cut()
  finally:
    if os.path.exists(image_path):
      os.remove(image_path)


def main():
  parser = argparse.ArgumentParser(description="Print new input entries from log.json on macOS.")
  parser.add_argument("--log-path", default="log.json", help="Path to source log JSON file.")
  parser.add_argument(
    "--state-path",
    default="printed_ids.json",
    help="Path to JSON file that tracks printed entry ids.",
  )
  parser.add_argument("--printer", default=None, help="Printer name for lp -d.")
  parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds.")
  parser.add_argument(
    "--backend",
    choices=["cups", "pos", "usb"],
    default="cups",
    help="Printing backend: cups (lp), pos (ESC/POS over network), or usb (python-escpos Usb).",
  )
  parser.add_argument("--pos-host", default=None, help="POS printer IP/hostname.")
  parser.add_argument("--pos-port", type=int, default=9100, help="POS printer TCP port.")
  parser.add_argument("--pos-timeout", type=float, default=3.0, help="POS connection timeout seconds.")
  parser.add_argument("--usb-vendor-id", default="0x0485", help="USB vendor id (default: 0x0485).")
  parser.add_argument("--usb-product-id", default="0x5741", help="USB product id (default: 0x5741).")
  parser.add_argument("--usb-interface", type=int, default=0, help="USB interface number (default: 0).")
  parser.add_argument("--usb-in-ep", default="0x81", help="USB IN endpoint (default: 0x81).")
  parser.add_argument("--usb-out-ep", default="0x03", help="USB OUT endpoint (default: 0x03).")
  parser.add_argument(
    "--usb-print-mode",
    choices=["image", "text"],
    default="image",
    help="USB print mode: image(recommended for Korean) or text.",
  )
  parser.add_argument("--usb-timeout-ms", type=int, default=3000, help="USB write timeout in ms.")
  parser.add_argument("--dry-run", action="store_true", help="Do not print; only log actions.")
  args = parser.parse_args()

  if args.backend == "pos" and not args.pos_host:
    raise SystemExit("--pos-host is required when --backend pos")

  usb_vendor_id = parse_hex_or_int(args.usb_vendor_id)
  usb_product_id = parse_hex_or_int(args.usb_product_id)
  usb_in_ep = parse_hex_or_int(args.usb_in_ep)
  usb_out_ep = parse_hex_or_int(args.usb_out_ep)

  printed_ids = set(load_json(args.state_path, []))

  if not os.path.exists(args.state_path):
    save_json(args.state_path, sorted(printed_ids))

  print("Printer worker started.")
  print(f"log path   : {args.log_path}")
  print(f"state path : {args.state_path}")
  print(f"printer    : {args.printer or '(default)'}")
  print(f"backend    : {args.backend}")
  if args.backend == "pos":
    print(f"pos target : {args.pos_host}:{args.pos_port}")
  if args.backend == "usb":
    print(f"usb id     : 0x{usb_vendor_id:04x}:0x{usb_product_id:04x}")
    print(f"usb iface  : {args.usb_interface}")
    print(f"usb ep     : in=0x{usb_in_ep:02x} out=0x{usb_out_ep:02x}")
    print(f"usb mode   : {args.usb_print_mode}")
  print(f"interval   : {args.interval}s")
  print(f"dry run    : {args.dry_run}")

  while True:
    entries = load_json(args.log_path, [])
    if not isinstance(entries, list):
      entries = []

    has_new = False
    for entry in entries:
      if not isinstance(entry, dict):
        continue
      entry_id = entry.get("id")
      value = entry.get("value")
      if not entry_id or not isinstance(value, str) or not value.strip():
        continue
      if entry_id in printed_ids:
        continue

      text = format_print_text(entry)
      try:
        if args.dry_run:
          print(f"[DRY RUN] Would print id={entry_id} value={value!r}")
        else:
          if args.backend == "cups":
            print_entry(text, printer_name=args.printer)
          elif args.backend == "pos":
            print_entry_pos(
              entry=entry,
              host=args.pos_host,
              port=args.pos_port,
              timeout=args.pos_timeout,
            )
          else:
            if args.usb_print_mode == "image":
              print_entry_usb_image(
                entry=entry,
                vendor_id=usb_vendor_id,
                product_id=usb_product_id,
                interface=args.usb_interface,
                in_ep=usb_in_ep,
                out_ep=usb_out_ep,
                timeout_ms=args.usb_timeout_ms,
              )
            else:
              print_entry_usb_escpos(
                entry=entry,
                vendor_id=usb_vendor_id,
                product_id=usb_product_id,
                interface=args.usb_interface,
                in_ep=usb_in_ep,
                out_ep=usb_out_ep,
                timeout_ms=args.usb_timeout_ms,
              )
          print(f"Printed id={entry_id}")
        printed_ids.add(entry_id)
        has_new = True
      except subprocess.CalledProcessError as e:
        stderr = (e.stderr or "").strip()
        print(f"Print failed for id={entry_id}: {stderr}")
      except RuntimeError as e:
        message = str(e).strip() or repr(e)
        print(f"Runtime error for id={entry_id}: {message}")
        if "usb library" in message.lower() or "dependencies for usb" in message.lower():
          print("Missing USB dependencies. Install pyusb + libusb, then restart worker.")
          return
      except Exception as e:
        message = str(e).strip() or repr(e)
        print(f"Unexpected error for id={entry_id}: {message}")

    if has_new:
      save_json(args.state_path, sorted(printed_ids))

    time.sleep(args.interval)


if __name__ == "__main__":
  main()
