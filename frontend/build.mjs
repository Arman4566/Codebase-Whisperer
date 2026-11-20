// Bundles the React app (React included) into whisperer/static/app.js + app.css.
// Usage: npm install && npm run build
import { build } from "esbuild";

await build({
  entryPoints: ["src/main.jsx"],
  bundle: true,
  minify: true,
  outfile: "../whisperer/static/app.js",
  jsx: "automatic",
  target: ["es2019"],
  define: { "process.env.NODE_ENV": '"production"' },
  legalComments: "none",
  logLevel: "info",
});
