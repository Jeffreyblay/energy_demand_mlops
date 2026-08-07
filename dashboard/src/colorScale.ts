// GridVision — the one sequential blue ramp used everywhere demand magnitude
// is encoded: the map's columns/glow, this module's hex output for the
// sidebar swatch. Shared so "more demand = darker blue" means the same thing
// on the map as it does next to a region's name.
export const RAMP: [number, [number, number, number]][] = [
  [0, [183, 211, 246]],
  [15000, [109, 167, 236]],
  [40000, [42, 120, 214]],
  [80000, [24, 79, 149]],
  [130000, [13, 54, 107]],
];

export function colorForDemandRGB(mw: number): [number, number, number] {
  for (let i = 1; i < RAMP.length; i++) {
    const [hiStop, hiColor] = RAMP[i];
    if (mw <= hiStop) {
      const [loStop, loColor] = RAMP[i - 1];
      const t = (mw - loStop) / (hiStop - loStop || 1);
      return [0, 1, 2].map((c) => Math.round(loColor[c] + (hiColor[c] - loColor[c]) * t)) as [number, number, number];
    }
  }
  return RAMP[RAMP.length - 1][1];
}

export function colorForDemandHex(mw: number): string {
  const [r, g, b] = colorForDemandRGB(mw);
  return `#${[r, g, b].map((c) => c.toString(16).padStart(2, "0")).join("")}`;
}
