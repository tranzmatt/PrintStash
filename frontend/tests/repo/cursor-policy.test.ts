/** Ordinary action cursors have one policy; component overrides cannot drift. */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const root = resolve(import.meta.dirname, "../..");

function sources(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const filename = join(directory, entry.name);
    if (entry.isDirectory()) return entry.name === "__tests__" ? [] : sources(filename);
    return /\.(tsx?|css)$/.test(entry.name) && !/\.(test|spec)\./.test(entry.name)
      ? [filename]
      : [];
  });
}

describe("cursor policy", () => {
  it("keeps ordinary cursor overrides out of components", () => {
    const files = ["src/components", "src/pages", "packages/ui/src"].flatMap((directory) =>
      sources(resolve(root, directory)),
    );
    const findings = files.flatMap((filename) => {
      const source = readFileSync(filename, "utf8");
      const ordinaryUtility =
        /\bcursor-(pointer|default|not-allowed)\b|\bcursor-\[(pointer|default|not-allowed)\]/;
      const inlineValue = /(?:\bcursor\s*:|\.cursor\s*=)\s*["'](pointer|default|not-allowed)["']/;
      const cssValue = /\bcursor\s*:\s*(pointer|default|not-allowed)\s*[;}]/;
      return ordinaryUtility.test(source) || inlineValue.test(source) || cssValue.test(source)
        ? [relative(root, filename)]
        : [];
    });

    expect(findings).toEqual([]);
  });
});
