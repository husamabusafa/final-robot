/**
 * Starts the relay and the Vite dev server together, so `npm run dev` is one
 * command. Kept dependency-free on purpose.
 */
import { spawn } from "node:child_process";

const children = [];

function run(name, cmd, args, env) {
  const child = spawn(cmd, args, {
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, ...env },
  });
  const tag = `[${name}] `;
  const pipe = (stream, out) => {
    stream.setEncoding("utf8");
    let buf = "";
    stream.on("data", (chunk) => {
      buf += chunk;
      const lines = buf.split("\n");
      buf = lines.pop() ?? "";
      for (const line of lines) out.write(tag + line + "\n");
    });
  };
  pipe(child.stdout, process.stdout);
  pipe(child.stderr, process.stderr);
  child.on("exit", (code) => {
    process.stdout.write(`${tag}exited with ${code}\n`);
    shutdown(code ?? 0);
  });
  children.push(child);
}

function shutdown(code) {
  for (const c of children) if (!c.killed) c.kill("SIGTERM");
  process.exit(code);
}

process.on("SIGINT", () => shutdown(0));
process.on("SIGTERM", () => shutdown(0));

run("relay", process.execPath, ["--watch", "server/index.ts"], {
  PORT: "4001",
  SERVE_STATIC: "false",
  HSAFA_PANEL_TOKEN: process.env.HSAFA_PANEL_TOKEN ?? "dev-token",
});
run("vite", process.execPath, ["node_modules/vite/bin/vite.js"], {});

process.stdout.write(
  "\n  panel  -> http://localhost:5173\n  relay  -> ws://localhost:4001/robot?token=dev-token\n\n",
);
