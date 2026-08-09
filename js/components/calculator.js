// A self-contained graphing calculator for the math modules.
//
// No external library: expressions are tokenized and compiled to RPN here, and
// plotting is plain canvas. That keeps the whole app dependency-free and working
// offline. Expressions are never passed to eval() — the evaluator only knows the
// operators and functions listed below.

const FUNCTIONS = {
  sin: Math.sin,
  cos: Math.cos,
  tan: Math.tan,
  asin: Math.asin,
  acos: Math.acos,
  atan: Math.atan,
  sqrt: Math.sqrt,
  abs: Math.abs,
  ln: Math.log,
  log: Math.log10,
  exp: Math.exp,
  floor: Math.floor,
  ceil: Math.ceil,
  round: Math.round,
};

const CONSTANTS = { pi: Math.PI, e: Math.E, 'π': Math.PI };

const OPERATORS = {
  '+': { precedence: 1, right: false, apply: (a, b) => a + b },
  '-': { precedence: 1, right: false, apply: (a, b) => a - b },
  '*': { precedence: 2, right: false, apply: (a, b) => a * b },
  '/': { precedence: 2, right: false, apply: (a, b) => a / b },
  '%': { precedence: 2, right: false, apply: (a, b) => a % b },
  '^': { precedence: 4, right: true, apply: (a, b) => a ** b },
};

// Unary minus sits between * and ^, so -3^2 is -(3^2) = -9, matching standard
// math notation and every graphing calculator.
const UNARY_PRECEDENCE = 3;

// ─────────────────────────────── parsing ───────────────────────────────

function tokenize(source) {
  const tokens = [];
  let i = 0;
  const text = source.replace(/−/g, '-').replace(/×/g, '*').replace(/÷/g, '/');

  while (i < text.length) {
    const char = text[i];

    if (/\s/.test(char)) {
      i += 1;
    } else if (/[0-9.]/.test(char)) {
      let j = i;
      while (j < text.length && /[0-9.]/.test(text[j])) j += 1;
      const value = Number(text.slice(i, j));
      if (!Number.isFinite(value)) throw new Error(`bad number "${text.slice(i, j)}"`);
      tokens.push({ type: 'number', value });
      i = j;
    } else if (/[a-zA-Zπ]/.test(char)) {
      let j = i;
      while (j < text.length && /[a-zA-Z0-9_π]/.test(text[j])) j += 1;
      tokens.push({ type: 'name', value: text.slice(i, j) });
      i = j;
    } else if (char in OPERATORS) {
      tokens.push({ type: 'operator', value: char });
      i += 1;
    } else if (char === '(' || char === ')') {
      tokens.push({ type: char });
      i += 1;
    } else if (char === ',') {
      tokens.push({ type: 'comma' });
      i += 1;
    } else {
      throw new Error(`unexpected character "${char}"`);
    }
  }
  return tokens;
}

/** Insert explicit multiplication so "2x", "3(x+1)" and "2sin(x)" work. */
function withImplicitMultiplication(tokens) {
  const out = [];
  for (let i = 0; i < tokens.length; i += 1) {
    const token = tokens[i];
    const next = tokens[i + 1];
    out.push(token);
    if (!next) continue;

    const isFunction = token.type === 'name' && token.value in FUNCTIONS;
    const endsValue = token.type === 'number' || token.type === ')' || (token.type === 'name' && !isFunction);
    const startsValue = next.type === 'number' || next.type === 'name' || next.type === '(';
    if (endsValue && startsValue) out.push({ type: 'operator', value: '*' });
  }
  return out;
}

/** Compile to RPN once; evaluating per pixel then costs no parsing. */
function compile(source) {
  const tokens = withImplicitMultiplication(tokenize(source));
  const output = [];
  const stack = [];
  let expectValue = true; // distinguishes unary minus from subtraction

  for (const token of tokens) {
    if (token.type === 'number') {
      output.push(token);
      expectValue = false;
    } else if (token.type === 'name') {
      if (token.value in FUNCTIONS) {
        stack.push({ type: 'function', value: token.value });
        expectValue = true;
      } else {
        const lower = token.value.toLowerCase();
        if (lower === 'x') output.push({ type: 'variable' });
        else if (lower in CONSTANTS) output.push({ type: 'number', value: CONSTANTS[lower] });
        else if (token.value in CONSTANTS) output.push({ type: 'number', value: CONSTANTS[token.value] });
        else throw new Error(`unknown name "${token.value}"`);
        expectValue = false;
      }
    } else if (token.type === 'operator') {
      if (token.value === '-' && expectValue) {
        stack.push({ type: 'unary' });
      } else {
        const op = OPERATORS[token.value];
        while (stack.length) {
          const top = stack[stack.length - 1];
          if (top.type === '(') break;
          const topPrecedence =
            top.type === 'function'
              ? Infinity
              : top.type === 'unary'
                ? UNARY_PRECEDENCE
                : OPERATORS[top.value].precedence;
          const higher =
            topPrecedence > op.precedence || (topPrecedence === op.precedence && !op.right);
          if (!higher) break;
          output.push(stack.pop());
        }
        stack.push(token);
      }
      expectValue = true;
    } else if (token.type === '(') {
      stack.push(token);
      expectValue = true;
    } else if (token.type === ')') {
      while (stack.length && stack[stack.length - 1].type !== '(') output.push(stack.pop());
      if (!stack.length) throw new Error('unbalanced parentheses');
      stack.pop();
      if (stack.length && stack[stack.length - 1].type === 'function') output.push(stack.pop());
      expectValue = false;
    } else if (token.type === 'comma') {
      while (stack.length && stack[stack.length - 1].type !== '(') output.push(stack.pop());
      expectValue = true;
    }
  }

  while (stack.length) {
    const top = stack.pop();
    if (top.type === '(') throw new Error('unbalanced parentheses');
    output.push(top);
  }
  if (!output.length) throw new Error('empty expression');

  // Walk the RPN and check every operator has its operands, so a half-typed
  // expression like "2+" reports an error instead of silently plotting nothing.
  let depth = 0;
  for (const token of output) {
    if (token.type === 'number' || token.type === 'variable') depth += 1;
    else if (token.type === 'unary' || token.type === 'function') {
      if (depth < 1) throw new Error('incomplete expression');
    } else if (token.type === 'operator') {
      if (depth < 2) throw new Error('incomplete expression');
      depth -= 1;
    }
  }
  if (depth !== 1) throw new Error('incomplete expression');

  const usesX = output.some((t) => t.type === 'variable');
  return { rpn: output, usesX };
}

function evaluate(rpn, x) {
  const stack = [];
  for (const token of rpn) {
    if (token.type === 'number') stack.push(token.value);
    else if (token.type === 'variable') stack.push(x);
    else if (token.type === 'unary') {
      if (!stack.length) return NaN;
      stack.push(-stack.pop());
    } else if (token.type === 'function') {
      if (!stack.length) return NaN;
      stack.push(FUNCTIONS[token.value](stack.pop()));
    } else if (token.type === 'operator') {
      if (stack.length < 2) return NaN;
      const b = stack.pop();
      const a = stack.pop();
      stack.push(OPERATORS[token.value].apply(a, b));
    }
  }
  return stack.length === 1 ? stack[0] : NaN;
}

// ─────────────────────────────── the widget ───────────────────────────────

const COLORS = ['#0891b2', '#7c5cff', '#c2740a', '#0e9f6e'];

/** Canvas can't use CSS variables, so read the resolved theme colours out. */
function themeColors() {
  const style = getComputedStyle(document.documentElement);
  const read = (name, fallback) => style.getPropertyValue(name).trim() || fallback;
  return {
    canvas: read('--canvas', '#0b0e1c'),
    grid: read('--grid-line', '#1c2140'),
    axis: read('--grid-axis', '#4b5280'),
    label: read('--dim', '#6f76a3'),
    trace: read('--muted', '#9aa0c4'),
  };
}
const START_VIEW = { xMin: -10, xMax: 10, yMin: -10, yMax: 10 };

/** "Nice" gridline spacing: 1, 2 or 5 times a power of ten. */
function gridStep(range, targetLines) {
  const rough = range / targetLines;
  const magnitude = 10 ** Math.floor(Math.log10(rough));
  const normalized = rough / magnitude;
  const factor = normalized < 1.5 ? 1 : normalized < 3 ? 2 : normalized < 7 ? 5 : 10;
  return factor * magnitude;
}

const format = (value) => {
  if (!Number.isFinite(value)) return '—';
  if (value === 0) return '0';
  if (Math.abs(value) >= 1e6 || Math.abs(value) < 1e-4) return value.toExponential(3);
  return String(Math.round(value * 1e6) / 1e6);
};

export function createCalculator(host) {
  const rows = [
    { source: '', color: COLORS[0] },
    { source: '', color: COLORS[1] },
  ];
  const view = { ...START_VIEW };
  let hoverX = null;

  host.innerHTML = `
    <div class="calc">
      <div class="calc-graph">
        <canvas class="calc-canvas"></canvas>
        <div class="calc-zoom">
          <button type="button" data-zoom="in" title="Zoom in">+</button>
          <button type="button" data-zoom="out" title="Zoom out">−</button>
          <button type="button" data-zoom="reset" title="Reset view">⌖</button>
        </div>
        <div class="calc-readout" aria-live="polite"></div>
      </div>
      <div class="calc-side">
        <div class="calc-rows"></div>
        <div class="calc-keys">
          ${['(', ')', '^', '/', 'sqrt(', 'abs(', 'sin(', 'cos(', 'tan(', 'ln(', 'log(', 'pi']
            .map((key) => {
              // Show function keys without their opening paren, but keep "(" itself.
              const label = key.length > 1 && key.endsWith('(') ? key.slice(0, -1) : key;
              return `<button type="button" data-key="${key}">${label}</button>`;
            })
            .join('')}
        </div>
        <p class="calc-hint">
          Type an expression in x to graph it, or one without x to evaluate it.
          Drag to pan, scroll to zoom.
        </p>
      </div>
    </div>`;

  const canvas = host.querySelector('.calc-canvas');
  const context = canvas.getContext('2d');
  const readout = host.querySelector('.calc-readout');
  const rowsHost = host.querySelector('.calc-rows');
  let lastFocused = 0;

  function paintRows() {
    rowsHost.innerHTML = rows
      .map(
        (row, index) => `
        <div class="calc-row ${row.error ? 'is-error' : ''}">
          <span class="calc-swatch" style="background:${row.color}"></span>
          <input type="text" value="${row.source.replace(/"/g, '&quot;')}"
                 data-index="${index}" spellcheck="false" placeholder="${index === 0 ? 'x^2 - 3' : 'expression'}"
                 aria-label="Expression ${index + 1}" />
          <span class="calc-value">${row.error ? row.error : row.value ?? ''}</span>
        </div>`,
      )
      .join('');
  }

  function compileRows() {
    for (const row of rows) {
      row.compiled = null;
      row.error = '';
      row.value = '';
      if (!row.source.trim()) continue;
      try {
        row.compiled = compile(row.source);
        if (!row.compiled.usesX) {
          const value = evaluate(row.compiled.rpn, 0);
          row.value = format(value);
        }
      } catch (error) {
        row.error = error.message;
      }
    }
  }

  function sizeCanvas() {
    const ratio = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width = Math.max(1, Math.round(rect.width * ratio));
    canvas.height = Math.max(1, Math.round(rect.height * ratio));
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    return rect;
  }

  function draw() {
    const rect = sizeCanvas();
    const { width, height } = rect;
    const toPixelX = (x) => ((x - view.xMin) / (view.xMax - view.xMin)) * width;
    const toPixelY = (y) => height - ((y - view.yMin) / (view.yMax - view.yMin)) * height;
    const toValueX = (px) => view.xMin + (px / width) * (view.xMax - view.xMin);

    const theme = themeColors();
    context.clearRect(0, 0, width, height);
    context.fillStyle = theme.canvas;
    context.fillRect(0, 0, width, height);

    // Grid and labels
    const stepX = gridStep(view.xMax - view.xMin, Math.max(4, Math.round(width / 70)));
    const stepY = gridStep(view.yMax - view.yMin, Math.max(4, Math.round(height / 55)));
    context.font = '10px ui-sans-serif, system-ui, sans-serif';
    context.lineWidth = 1;

    for (let x = Math.ceil(view.xMin / stepX) * stepX; x <= view.xMax; x += stepX) {
      const px = toPixelX(x);
      context.strokeStyle = Math.abs(x) < stepX / 1000 ? theme.axis : theme.grid;
      context.beginPath();
      context.moveTo(px, 0);
      context.lineTo(px, height);
      context.stroke();
      if (Math.abs(x) > stepX / 1000) {
        context.fillStyle = theme.label;
        context.fillText(format(x), px + 3, toPixelY(0) - 4 > 12 ? toPixelY(0) - 4 : 12);
      }
    }
    for (let y = Math.ceil(view.yMin / stepY) * stepY; y <= view.yMax; y += stepY) {
      const py = toPixelY(y);
      context.strokeStyle = Math.abs(y) < stepY / 1000 ? theme.axis : theme.grid;
      context.beginPath();
      context.moveTo(0, py);
      context.lineTo(width, py);
      context.stroke();
      if (Math.abs(y) > stepY / 1000) {
        context.fillStyle = '#6f76a3';
        const labelX = Math.min(Math.max(toPixelX(0) + 4, 4), width - 34);
        context.fillText(format(y), labelX, py - 3);
      }
    }

    // Curves
    const hoverValues = [];
    for (const row of rows) {
      if (!row.compiled?.usesX) continue;
      context.strokeStyle = row.color;
      context.lineWidth = 2;
      context.beginPath();
      let drawing = false;
      let previousY = null;

      for (let px = 0; px <= width; px += 1) {
        const y = evaluate(row.compiled.rpn, toValueX(px));
        if (!Number.isFinite(y)) {
          drawing = false;
          previousY = null;
          continue;
        }
        const py = toPixelY(y);
        // Break the stroke across asymptotes instead of drawing a vertical line.
        const jumped = previousY !== null && Math.abs(py - previousY) > height * 1.5;
        if (!drawing || jumped) {
          context.moveTo(px, py);
          drawing = true;
        } else {
          context.lineTo(px, py);
        }
        previousY = py;
      }
      context.stroke();

      if (hoverX !== null) {
        hoverValues.push({ color: row.color, y: evaluate(row.compiled.rpn, hoverX) });
      }
    }

    if (hoverX !== null && hoverValues.length) {
      const px = toPixelX(hoverX);
      context.strokeStyle = theme.trace;
      context.lineWidth = 1;
      context.beginPath();
      context.moveTo(px, 0);
      context.lineTo(px, height);
      context.stroke();
      for (const { color, y } of hoverValues) {
        if (!Number.isFinite(y)) continue;
        context.fillStyle = color;
        context.beginPath();
        context.arc(px, toPixelY(y), 3.5, 0, Math.PI * 2);
        context.fill();
      }
      readout.innerHTML =
        `<span>x = ${format(hoverX)}</span>` +
        hoverValues
          .map(({ color, y }) => `<span style="color:${color}">y = ${format(y)}</span>`)
          .join('');
    } else {
      readout.innerHTML = '<span>Hover the graph to trace</span>';
    }
  }

  function refresh() {
    compileRows();
    paintRows();
    draw();
  }

  function zoom(factor, anchorX = (view.xMin + view.xMax) / 2, anchorY = (view.yMin + view.yMax) / 2) {
    view.xMin = anchorX + (view.xMin - anchorX) * factor;
    view.xMax = anchorX + (view.xMax - anchorX) * factor;
    view.yMin = anchorY + (view.yMin - anchorY) * factor;
    view.yMax = anchorY + (view.yMax - anchorY) * factor;
    draw();
  }

  // ── events ──
  const onInput = (event) => {
    const input = event.target.closest('input[data-index]');
    if (!input) return;
    lastFocused = Number(input.dataset.index);
    rows[lastFocused].source = input.value;
    compileRows();
    // Update just the value/error text so typing doesn't lose caret position.
    const row = rows[lastFocused];
    const cell = input.parentElement.querySelector('.calc-value');
    if (cell) cell.textContent = row.error || row.value || '';
    input.parentElement.classList.toggle('is-error', Boolean(row.error));
    draw();
  };

  const onFocus = (event) => {
    const input = event.target.closest('input[data-index]');
    if (input) lastFocused = Number(input.dataset.index);
  };

  const onClick = (event) => {
    const zoomButton = event.target.closest('[data-zoom]');
    if (zoomButton) {
      const action = zoomButton.dataset.zoom;
      if (action === 'in') zoom(0.7);
      else if (action === 'out') zoom(1 / 0.7);
      else {
        Object.assign(view, START_VIEW);
        draw();
      }
      return;
    }
    const key = event.target.closest('[data-key]');
    if (key) {
      const input = rowsHost.querySelector(`input[data-index="${lastFocused}"]`);
      if (!input) return;
      rows[lastFocused].source += key.dataset.key;
      input.value = rows[lastFocused].source;
      input.focus();
      refresh();
      rowsHost.querySelector(`input[data-index="${lastFocused}"]`)?.focus();
    }
  };

  let dragging = null;
  const onPointerDown = (event) => {
    dragging = { x: event.clientX, y: event.clientY, view: { ...view } };
    canvas.setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event) => {
    const rect = canvas.getBoundingClientRect();
    if (dragging) {
      const dx = ((event.clientX - dragging.x) / rect.width) * (dragging.view.xMax - dragging.view.xMin);
      const dy = ((event.clientY - dragging.y) / rect.height) * (dragging.view.yMax - dragging.view.yMin);
      view.xMin = dragging.view.xMin - dx;
      view.xMax = dragging.view.xMax - dx;
      view.yMin = dragging.view.yMin + dy;
      view.yMax = dragging.view.yMax + dy;
      hoverX = null;
    } else {
      hoverX = view.xMin + ((event.clientX - rect.left) / rect.width) * (view.xMax - view.xMin);
    }
    draw();
  };
  const onPointerUp = () => {
    dragging = null;
  };
  const onLeave = () => {
    hoverX = null;
    draw();
  };
  const onWheel = (event) => {
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const anchorX = view.xMin + ((event.clientX - rect.left) / rect.width) * (view.xMax - view.xMin);
    const anchorY = view.yMax - ((event.clientY - rect.top) / rect.height) * (view.yMax - view.yMin);
    zoom(event.deltaY > 0 ? 1.12 : 1 / 1.12, anchorX, anchorY);
  };
  const onResize = () => draw();

  host.addEventListener('input', onInput);
  host.addEventListener('focusin', onFocus);
  host.addEventListener('click', onClick);
  canvas.addEventListener('pointerdown', onPointerDown);
  canvas.addEventListener('pointermove', onPointerMove);
  canvas.addEventListener('pointerup', onPointerUp);
  canvas.addEventListener('pointerleave', onLeave);
  canvas.addEventListener('wheel', onWheel, { passive: false });
  window.addEventListener('resize', onResize);

  refresh();

  return {
    destroy() {
      host.removeEventListener('input', onInput);
      host.removeEventListener('focusin', onFocus);
      host.removeEventListener('click', onClick);
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('pointerleave', onLeave);
      canvas.removeEventListener('wheel', onWheel);
      window.removeEventListener('resize', onResize);
      host.innerHTML = '';
    },
    redraw: draw,
  };
}

// Exported for testing the parser without a DOM.
export const __parser = { compile, evaluate };
