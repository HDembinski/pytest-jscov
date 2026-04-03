declare const dialog: ParentNode & { innerHTML: string };

dialog.innerHTML = `<dialog>
</dialog>`;

const foo = dialog.querySelector(
    ".foo"
) as HTMLDivElement;