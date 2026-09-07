// Loads the repo-root .env (gitignored) for every script under scripts/.
// Import this FIRST: `import "./_env.ts";` (or "../_env.ts" from probe/).
import { config } from "dotenv";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
config({ path: resolve(HERE, "../.env"), quiet: true });
