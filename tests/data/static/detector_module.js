// this is a comment
const fallback = "fallback";

/* this is a mulit
line comment */

export function compute(flag) {
  if (flag) return fallback.toUpperCase();
  return fallback;
}
export const unusedValue = compute(false);
