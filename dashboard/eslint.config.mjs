import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  ...compat.extends("next/core-web-vitals", "next/typescript"),
  {
    // .next-staging is the staging build output (see next.config.ts distDir).
    // Without it here, eslint lints minified build artifacts and the lint gate
    // fails with thousands of errors in generated code.
    ignores: [".next/**", ".next-staging/**", "out/**", "build/**", "next-env.d.ts"],
  },
];

export default eslintConfig;
