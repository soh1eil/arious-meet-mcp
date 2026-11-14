import { type ChildProcess, spawn } from "node:child_process";
import { randomBytes } from "node:crypto";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const MOCK = join(here, "..", "..", "..", "mock", "server.py");

let proc: ChildProcess | null = null;

/** Start the shared Python mock once per test file; returns its /v1/mcp URL. */
export async function startMock(): Promise<string> {
  proc = spawn("python3", [MOCK, "--port", "0"], {
    stdio: ["ignore", "pipe", "inherit"],
  });
  const url = await new Promise<string>((resolve, reject) => {
    proc?.stdout?.once("data", (d: Buffer) => resolve(String(d).trim().split(" ")[1] ?? ""));
    proc?.once("error", reject);
  });
  return url;
}

export function stopMock(): void {
  proc?.kill();
}

export const token = () => `test-${randomBytes(8).toString("hex")}`;

export async function push(url: string, tok: string, items: unknown[]): Promise<void> {
  await fetch(url.replace("/v1/mcp", "/__mock/push"), {
    method: "POST",
    body: JSON.stringify({ token: tok, items }),
  });
}

/** fetch wrapper that pins the mock's mode per request via a header. */
export function modeFetch(mode: string): typeof fetch {
  return (input, init) => {
    const headers = new Headers(init?.headers);
    headers.set("X-Mock-Mode", mode);
    return fetch(input, { ...init, headers });
  };
}
