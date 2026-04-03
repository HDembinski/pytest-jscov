// this is a comment
const prefix = "// not a comment";

/* this is a mulit
line comment */

function choose(name) {
  if (name) return `${prefix}:${name}`; // inline comment
  return "nobody";
}

globalThis.__detectorClassic = choose;
