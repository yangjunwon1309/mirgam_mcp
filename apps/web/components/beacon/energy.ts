export const ENERGY_DEFAULTS = { usableMah: 1560, activeMa: 120, camMa: 160, offUa: 20, fastS: 1.5, imageS: 1.2, imagesPerDay: 24 };
export function estimateDays(intervalS: number, withImage: boolean, c = ENERGY_DEFAULTS): number {
  const checkin = (86400 / intervalS) * c.activeMa * c.fastS / 3600;
  const images = withImage ? c.imagesPerDay * c.camMa * c.imageS / 3600 : 0;
  const off = c.offUa * 24 / 1000;
  return c.usableMah / (checkin + images + off);
}
export function daysLabel(d: number): string { return d > 365 ? "1년 이상" : "약 " + Math.round(d) + "일"; }
