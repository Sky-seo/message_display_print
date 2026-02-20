// Main controls:
// 1) How fast text falls
let FALL_SPEED = 0.5;
// 2) How much text drifts left/right
let HORIZONTAL_DRIFT = 0.9;
// 3) 착지 후 기울어지는 정도(라디안)
let MAX_TILT = 0.2;

const GRAVITY = 0.08;
const FLOOR_MARGIN = 60;
const FONT_SIZE = 24;
const MIN_COLLISION_OVERLAP_RATIO = 0.08;
const MAX_STACK_ITEMS = 100;
const INPUT_POLL_INTERVAL_MS = 500;

const flakes = [];
const seenInputKeys = new Set();
let hasInitializedInputs = false;
let pollInFlight = false;

function setup() {
  createCanvas(windowWidth, windowHeight);
  textFont('Arial');
  textSize(FONT_SIZE);
  textAlign(CENTER, TOP);
  startInputPolling();
}

function addFlake(label) {
  const padding = 14;
  textSize(FONT_SIZE);
  const w = textWidth(label) + padding;
  const h = FONT_SIZE + 6;

  flakes.push({
    label,
    x: random(0, width),
    y: -h - random(10, 70),
    w,
    h,
    vx: random(-0.2, 0.2),
    vy: random(0.2, 0.9),
    phase: random(TWO_PI),
    landed: false,
    angle: random(-0.08, 0.08),
    av: random(-0.01, 0.01),
    targetAngle: 0,
    slideV: 0
  });

  // Always keep only the latest MAX_STACK_ITEMS on screen.
  while (flakes.length > MAX_STACK_ITEMS) {
    flakes.shift();
  }
}

function draw() {
  background(17);

  drawFloor();
  updateFlakes();
  drawFlakes();
}

function getInputKey(item) {
  if (typeof item.id === 'string' && item.id.length > 0) return item.id;
  return `${item.createdAt || 'no-time'}:${item.value || ''}`;
}

async function fetchInputs() {
  const response = await fetch('/api/inputs');
  if (!response.ok) throw new Error(`Failed to fetch inputs: ${response.status}`);
  return response.json();
}

async function pollInputs() {
  if (pollInFlight) return;
  pollInFlight = true;

  try {
    const inputs = await fetchInputs();
    if (!Array.isArray(inputs)) return;

    const latestKeys = [];
    for (let i = 0; i < inputs.length; i += 1) {
      const item = inputs[i];
      const key = getInputKey(item);
      latestKeys.push(key);
      if (!hasInitializedInputs) {
        seenInputKeys.add(key);
        continue;
      }

      if (!seenInputKeys.has(key) && typeof item.value === 'string' && item.value.trim()) {
        seenInputKeys.add(key);
        addFlake(item.value.trim());
      }
    }

    const latestSet = new Set(latestKeys);
    for (const key of seenInputKeys) {
      if (!latestSet.has(key)) seenInputKeys.delete(key);
    }

    hasInitializedInputs = true;
  } catch (error) {
    console.warn(error);
  } finally {
    pollInFlight = false;
  }
}

function startInputPolling() {
  pollInputs();
  setInterval(pollInputs, INPUT_POLL_INTERVAL_MS);
}

function drawFloor() {
  noStroke();
  fill(35);
  rect(0, height - FLOOR_MARGIN, width, FLOOR_MARGIN);
}

function updateFlakes() {
  for (const flake of flakes) {
    if (flake.landed) {
      continue;
    }

    flake.phase += 0.04;
    flake.vx += sin(flake.phase) * 0.03 * HORIZONTAL_DRIFT;
    flake.vx = constrain(flake.vx, -1.8 * HORIZONTAL_DRIFT, 1.8 * HORIZONTAL_DRIFT);
    flake.vy += GRAVITY * FALL_SPEED;
    flake.av += flake.vx * 0.002;
    flake.av *= 0.99;
    flake.angle += flake.av;
    flake.angle = constrain(flake.angle, -MAX_TILT, MAX_TILT);

    const nextX = flake.x + flake.vx;
    const nextY = flake.y + flake.vy * FALL_SPEED;

    flake.x = constrain(nextX, flake.w / 2, width - flake.w / 2);
    const targetY = getCollisionTargetY(flake, flake.x, nextY);

    if (nextY >= targetY) {
      flake.y = targetY;
      const impactOffset = constrain(flake.vx * 0.7 + random(-0.3, 0.3), -1, 1);
      flake.x = constrain(
        flake.x + impactOffset * 4,
        flake.w / 2,
        width - flake.w / 2
      );
      flake.targetAngle = constrain(
        flake.angle + impactOffset * 0.25,
        -MAX_TILT,
        MAX_TILT
      );
      flake.av += impactOffset * 0.02;
      flake.vx = 0;
      flake.vy = 0;
      flake.slideV = 0;
      flake.landed = true;
    } else {
      flake.y = nextY;
    }
  }
}

function getCollisionTargetY(flake, testX, nextY) {
  let targetY = height - FLOOR_MARGIN - flake.h;
  const minOverlap = flake.w * MIN_COLLISION_OVERLAP_RATIO;

  for (const other of flakes) {
    if (!other.landed || other === flake) continue;

    const halfSpan = (flake.w + other.w) / 2;
    const distance = abs(testX - other.x);
    if (distance >= halfSpan) continue;

    const overlapWidth = halfSpan - distance;
    if (overlapWidth < minOverlap) continue;

    const hitsTop = flake.y + flake.h <= other.y && nextY + flake.h >= other.y;
    if (!hitsTop) continue;

    targetY = min(targetY, other.y - flake.h);
  }

  return targetY;
}

function drawFlakes() {
  noStroke();
  textSize(FONT_SIZE);
  for (const flake of flakes) {
    push();
    translate(flake.x, flake.y + flake.h / 2);
    rotate(flake.angle);
    fill(255);
    text(flake.label, 0, -flake.h / 2);
    pop();
  }
}

function windowResized() {
  resizeCanvas(windowWidth, windowHeight);
  for (const flake of flakes) {
    flake.x = constrain(flake.x, flake.w / 2, width - flake.w / 2);
  }
}
