/** Pydantic JSON Schema -> 表单可用结构。
 *
 * 后端给的是标准 JSON Schema（type 可能是 ["string","null"]、约束用 minimum/maximum），
 * 这里统一成组件好消费的形状，避免 ConfigPanel 里到处写兼容分支。
 */
import type { RawNodeSchema, RawSchemaProperty } from "@/api/nodeTypes";

export interface SchemaProperty {
  type: "string" | "number" | "integer" | "boolean" | "array";
  title?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minLength?: number;
}

export interface NormalizedSchema {
  properties: Record<string, SchemaProperty>;
  required: string[];
}

function pickType(prop: RawSchemaProperty): SchemaProperty["type"] {
  const raw = Array.isArray(prop.type) ? prop.type.find((item) => item !== "null") : prop.type;
  switch (raw) {
    case "number":
    case "integer":
    case "boolean":
    case "array":
      return raw;
    default:
      return "string";
  }
}

export function normalizeSchema(raw: RawNodeSchema | undefined): NormalizedSchema {
  const properties: Record<string, SchemaProperty> = {};
  for (const [key, prop] of Object.entries(raw?.properties ?? {})) {
    properties[key] = {
      type: pickType(prop),
      title: prop.title,
      description: prop.description,
      enum: prop.enum,
      default: prop.default,
      minimum: prop.minimum,
      maximum: prop.maximum,
      minLength: prop.minLength,
    };
  }
  return { properties, required: raw?.required ?? [] };
}
