// wiki-fabric OpenCode plugin
// Injects a knowledge-fabric reminder before bash tool calls when the fabric
// is connected (via .wiki-overlay.md). Modeled on graphify.js: fires once per
// session, prepends an echo so the reminder lands in tool output.
//
// IMPORTANT: keep the reminder string free of backticks and $(...) constructs —
// it is interpolated into a double-quoted echo, where backticks would trigger
// command substitution.
import { existsSync } from "fs";
import { join } from "path";

export const WikiFabricPlugin = async ({ directory }) => {
  let reminded = false;

  return {
    "tool.execute.before": async (input, output) => {
      if (reminded) return;
      if (!existsSync(join(directory, ".wiki-overlay.md"))) return;

      if (input.tool === "bash") {
        // ';' not '&&' — Windows PowerShell 5.1 rejects '&&' as a statement
        // separator, breaking the first bash command of the session.
        output.args.command =
          'echo "[wiki-fabric] knowledge fabric connected (.wiki-overlay.md). Before answering codebase/architecture questions run: wf context --task <task> (0 tokens) or wf query <question> (0 tokens). After solving a hard problem: wf log --project <slug>. Doc drift auto-captures on commit if the wf hook is installed." ; ' +
          output.args.command;
        reminded = true;
      }
    },
  };
};