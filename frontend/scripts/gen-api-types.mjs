#!/usr/bin/env node
/**
 * Generate TypeScript types for the backend contract.
 *
 * docs/api-protocol.md: the backend Pydantic models are the single source of
 * truth, so the frontend types are GENERATED from the backend OpenAPI schema
 * instead of being maintained by hand:
 *
 *   npm run gen:api            # fetch http://127.0.0.1:8000/openapi.json
 *   npm run gen:api -- --offline   # use scripts/openapi.snapshot.json only
 *
 * Behaviour:
 *   1. scripts/openapi.snapshot.json is always loaded. It is the frozen
 *      contract snapshot and keeps the build working while the backend is
 *      offline or has not implemented every endpoint yet.
 *   2. Unless --offline is passed, the live schema is fetched and merged on
 *      top of the snapshot (live definitions win, snapshot-only definitions
 *      are kept) so a running backend can never silently drop a model.
 *   3. src/api/schema.d.ts is written with one exported type per
 *      components.schemas entry. It is committed, so the app builds offline.
 *
 * Add --refresh-snapshot to rewrite scripts/openapi.snapshot.json from the
 * live backend after the backend route work lands.
 */

import { readFile, writeFile, mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "..");
const SNAPSHOT_PATH = resolve(HERE, "openapi.snapshot.json");
const OUT_PATH = resolve(ROOT, "src/api/schema.d.ts");

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const option = (name, fallback) => {
  const index = argv.indexOf(name);
  return index >= 0 && argv[index + 1] ? argv[index + 1] : fallback;
};

const URL_ = option("--url", process.env.API_OPENAPI_URL ?? "http://127.0.0.1:8000/openapi.json");
const OFFLINE = flag("--offline");
const REFRESH = flag("--refresh-snapshot");
const TIMEOUT_MS = Number(option("--timeout", "5000"));

/** Names that would shadow a global if they were imported directly. */
const RESERVED = new Set([
  "Error", "Event", "Date", "Object", "Array", "String", "Number", "Boolean",
  "Function", "Symbol", "Map", "Set", "Promise", "Record", "Partial", "Required",
  "Readonly", "Exclude", "Extract", "Pick", "Omit", "Request", "Response", "File",
  "Blob", "FormData", "Headers", "URL", "JSON",
]);

const safeName = (raw) => {
  const cleaned = String(raw).replace(/[^A-Za-z0-9_$]/g, "_");
  const named = /^[0-9]/.test(cleaned) ? "_" + cleaned : cleaned;
  return RESERVED.has(named) ? "Api" + named : named;
};

const refName = (ref) => safeName(String(ref).split("/").pop());
const isRecord = (value) => typeof value === "object" && value !== null && !Array.isArray(value);

function literalUnion(values) {
  return values
    .map((value) => (typeof value === "string" ? JSON.stringify(value) : String(value)))
    .join(" | ");
}

/** Render one (sub)schema as a TypeScript type expression. */
function tsType(schema) {
  if (schema === true || schema === undefined || schema === null) return "JsonValue";
  if (!isRecord(schema)) return "JsonValue";
  if (typeof schema.$ref === "string") return refName(schema.$ref);

  const branches = schema.oneOf ?? schema.anyOf;
  if (Array.isArray(branches) && branches.length > 0) {
    const parts = branches.map((branch) => tsType(branch));
    const unique = Array.from(new Set(parts));
    return unique.join(" | ");
  }
  if (Array.isArray(schema.allOf) && schema.allOf.length > 0) {
    return schema.allOf.map((branch) => tsType(branch)).join(" & ");
  }
  if (Array.isArray(schema.enum) && schema.enum.length > 0) {
    return literalUnion(schema.enum) + (schema.nullable ? " | null" : "");
  }
  if (schema.const !== undefined) {
    return typeof schema.const === "string" ? JSON.stringify(schema.const) : String(schema.const);
  }

  let base;
  switch (schema.type) {
    case "string":
      base = "string";
      break;
    case "integer":
    case "number":
      base = "number";
      break;
    case "boolean":
      base = "boolean";
      break;
    case "null":
      base = "null";
      break;
    case "array": {
      const items = tsType(schema.items ?? {});
      base = /^[A-Za-z0-9_$.]+$/.test(items) || items.endsWith("[]") ? items + "[]" : "(" + items + ")[]";
      break;
    }
    case "object":
    case undefined: {
      if (isRecord(schema.properties)) {
        base = inlineObject(schema);
      } else if (schema.additionalProperties && isRecord(schema.additionalProperties)) {
        base = "Record<string, " + tsType(schema.additionalProperties) + ">";
      } else if (schema.additionalProperties === true) {
        base = "Record<string, JsonValue>";
      } else {
        base = "JsonValue";
      }
      break;
    }
    default:
      base = "JsonValue";
  }
  if (schema.nullable === true && base !== "null") return base + " | null";
  return base;
}

function propertyKey(name) {
  return /^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name) ? name : JSON.stringify(name);
}

function inlineObject(schema, indent = "") {
  const required = new Set(Array.isArray(schema.required) ? schema.required : []);
  const entries = Object.entries(schema.properties ?? {});
  if (entries.length === 0) return "Record<string, JsonValue>";
  const lines = entries.map(([name, value]) => {
    const optional = required.has(name) ? "" : "?";
    return indent + "  " + propertyKey(name) + optional + ": " + tsType(value) + ";";
  });
  return "{\n" + lines.join("\n") + "\n" + indent + "}";
}

function docComment(schema, indent = "") {
  if (!schema || typeof schema.description !== "string" || schema.description.trim() === "") return "";
  return indent + "/** " + schema.description.trim().replace(/\*\//g, "*\\/") + " */\n";
}

/** Emit the whole schema file. */
function emit(schemas, meta) {
  const names = Object.keys(schemas).map(safeName).sort();
  const chunks = [];
  chunks.push(
    [
      "/* eslint-disable */",
      "// ---------------------------------------------------------------------------",
      "// GENERATED FILE - DO NOT EDIT BY HAND.",
      "//",
      "// Source: " + meta.source,
      "// Regenerate with: npm run gen:api  (see scripts/gen-api-types.mjs)",
      "//",
      "// The backend Pydantic models are the single source of truth",
      "// (docs/api-protocol.md), so every backend model exists exactly once, here.",
      "// ---------------------------------------------------------------------------",
      "",
      "/** Any JSON value the backend may put in an untyped field. */",
      "export type JsonValue =",
      "  | null",
      "  | boolean",
      "  | number",
      "  | string",
      "  | JsonValue[]",
      "  | { [key: string]: JsonValue };",
      "",
      "/** Every schema the backend published, addressable by name. */",
      "export interface ApiSchemas {",
      ...names.map((name) => "  " + name + ": " + name + ";"),
      "}",
      "",
    ].join("\n"),
  );

  for (const key of Object.keys(schemas).sort()) {
    const schema = schemas[key];
    const name = safeName(key);
    const header = docComment(schema);
    const isObjectInterface =
      isRecord(schema) &&
      (schema.type === "object" || isRecord(schema.properties)) &&
      !schema.oneOf &&
      !schema.anyOf &&
      !schema.allOf &&
      !schema.enum;

    if (isObjectInterface) {
      const required = new Set(Array.isArray(schema.required) ? schema.required : []);
      const entries = Object.entries(schema.properties ?? {});
      const body = entries.map(([prop, value]) => {
        const optional = required.has(prop) ? "" : "?";
        return docComment(value, "  ") + "  " + propertyKey(prop) + optional + ": " + tsType(value) + ";";
      });
      const lines = [header + "export interface " + name + " {"];
      if (body.length === 0) lines.push("  [key: string]: JsonValue;");
      else lines.push(...body);
      lines.push("}", "");
      chunks.push(lines.join("\n"));
    } else {
      chunks.push(header + "export type " + name + " = " + tsType(schema) + ";" + "\n");
    }
  }

  return chunks.join("\n");
}

async function fetchLive(url) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, { signal: controller.signal });
    if (!response.ok) throw new Error("HTTP " + response.status);
    const body = await response.json();
    if (!isRecord(body) || !isRecord(body.components) || !isRecord(body.components.schemas)) {
      throw new Error("payload has no components.schemas");
    }
    return body;
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  const snapshot = JSON.parse(await readFile(SNAPSHOT_PATH, "utf8"));
  let schemas = { ...(snapshot.components?.schemas ?? {}) };
  let source = "scripts/openapi.snapshot.json (frozen contract snapshot)";
  let live = null;

  if (!OFFLINE) {
    try {
      live = await fetchLive(URL_);
      const liveSchemas = live.components.schemas;
      const added = Object.keys(liveSchemas).filter((key) => !(key in schemas));
      schemas = { ...schemas, ...liveSchemas };
      source = URL_ + " (" + Object.keys(liveSchemas).length + " schemas, merged over the snapshot)";
      console.log("gen:api - fetched " + URL_);
      if (added.length > 0) console.log("gen:api - new schemas from the backend: " + added.join(", "));
    } catch (error) {
      console.log("gen:api - live schema unavailable (" + (error?.message ?? error) + "), using the snapshot");
    }
  } else {
    console.log("gen:api - offline mode: using the snapshot only");
  }

  const output = emit(schemas, { source });
  await mkdir(dirname(OUT_PATH), { recursive: true });
  await writeFile(OUT_PATH, output, "utf8");
  console.log("gen:api - wrote src/api/schema.d.ts (" + Object.keys(schemas).length + " schemas, " + output.length + " bytes)");

  if (REFRESH && live) {
    const refreshed = { ...snapshot, ...live, components: { ...live.components, schemas } };
    await writeFile(SNAPSHOT_PATH, JSON.stringify(refreshed, null, 2) + "\n", "utf8");
    console.log("gen:api - refreshed scripts/openapi.snapshot.json");
  }
}

main().catch((error) => {
  console.error("gen:api failed:", error);
  process.exit(1);
});
