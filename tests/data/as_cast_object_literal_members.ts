declare const holder: ParentNode;

const input = holder.querySelector("foo") as HTMLElement & {
    value: string;
    onkeyup: ((e: KeyboardEvent) => void) | null;
};