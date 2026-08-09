// The math reference panel, as the digital SAT provides one: the standard
// formulas and geometric facts, available during any math module.

const FIGURES = [
  {
    title: 'Circle',
    formulas: ['A = πr²', 'C = 2πr'],
    svg: `<circle cx="34" cy="34" r="26" /><line x1="34" y1="34" x2="60" y2="34" /><text x="44" y="30">r</text>`,
  },
  {
    title: 'Rectangle',
    formulas: ['A = ℓw'],
    svg: `<rect x="8" y="14" width="56" height="40" /><text x="33" y="10">ℓ</text><text x="68" y="38">w</text>`,
  },
  {
    title: 'Triangle',
    formulas: ['A = ½bh'],
    svg: `<polygon points="8,54 64,54 40,14" /><line x1="40" y1="14" x2="40" y2="54" stroke-dasharray="3 3" /><text x="44" y="38">h</text><text x="33" y="66">b</text>`,
  },
  {
    title: 'Right triangle',
    formulas: ['a² + b² = c²'],
    svg: `<polygon points="10,54 60,54 10,16" /><path d="M10 46 L18 46 L18 54" fill="none" /><text x="2" y="38">a</text><text x="33" y="66">b</text><text x="40" y="30">c</text>`,
  },
  {
    title: 'Special right triangles',
    formulas: ['30°–60°–90° → x, x√3, 2x', '45°–45°–90° → s, s, s√2'],
    svg: `<polygon points="8,54 46,54 8,20" /><text x="20" y="66">x√3</text><text x="0" y="40">x</text><text x="30" y="32">2x</text>`,
    wide: true,
  },
  {
    title: 'Rectangular solid',
    formulas: ['V = ℓwh'],
    svg: `<rect x="8" y="22" width="40" height="32" /><polygon points="8,22 20,10 60,10 48,22" /><polygon points="48,22 60,10 60,42 48,54" />`,
  },
  {
    title: 'Cylinder',
    formulas: ['V = πr²h'],
    svg: `<ellipse cx="34" cy="18" rx="20" ry="7" /><path d="M14 18 V50" /><path d="M54 18 V50" /><ellipse cx="34" cy="50" rx="20" ry="7" />`,
  },
  {
    title: 'Sphere',
    formulas: ['V = 4⁄3 πr³'],
    svg: `<circle cx="34" cy="34" r="24" /><ellipse cx="34" cy="34" rx="24" ry="8" stroke-dasharray="3 3" />`,
  },
  {
    title: 'Cone',
    formulas: ['V = 1⁄3 πr²h'],
    svg: `<ellipse cx="34" cy="50" rx="20" ry="7" /><path d="M14 50 L34 12 L54 50" fill="none" />`,
  },
  {
    title: 'Pyramid',
    formulas: ['V = 1⁄3 ℓwh'],
    svg: `<polygon points="10,50 58,50 34,12" /><path d="M10 50 L28 58 L58 50" fill="none" /><path d="M34 12 L28 58" stroke-dasharray="3 3" fill="none" />`,
  },
];

const FACTS = [
  'The number of degrees of arc in a circle is 360.',
  'The number of radians of arc in a circle is 2π.',
  'The sum of the measures in degrees of the angles of a triangle is 180.',
];

export function referenceSheet() {
  const cards = FIGURES.map(
    (figure) => `
      <div class="ref-card ${figure.wide ? 'is-wide' : ''}">
        <svg viewBox="0 0 72 72" aria-hidden="true" class="ref-svg">${figure.svg}</svg>
        <div class="ref-body">
          <strong>${figure.title}</strong>
          ${figure.formulas.map((f) => `<span>${f}</span>`).join('')}
        </div>
      </div>`,
  ).join('');

  return `
    <div class="ref-grid">${cards}</div>
    <ul class="ref-facts">${FACTS.map((f) => `<li>${f}</li>`).join('')}</ul>
    <p class="ref-note">All figures on the test are drawn to scale unless stated otherwise.</p>`;
}
