"use strict";

interface Person {
    name: string;
    age?: number;
}

type Label =
    | "a"
    | "b";

const label: Label = "a";
console.log(label);