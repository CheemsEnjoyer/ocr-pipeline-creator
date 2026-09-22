export const FIELD_TYPES = [
  ["string", "Текст"], ["number", "Число"], ["integer", "Целое число"],
  ["boolean", "Да / нет"], ["object", "Объект"], ["array", "Список объектов"],
];
export const isNested = (field) => ["object", "array"].includes(field.type);
export const newField = () => ({ name: "", type: "string", description: "", fields: [] });
export function validFields(fields, depth = 1) {
  const names = fields.map((field) => field.name.trim());
  return depth <= 6 && fields.length > 0 && names.every(Boolean) && new Set(names).size === names.length &&
    fields.every((field) => !isNested(field) || validFields(field.fields || [], depth + 1));
}
export function serializeFields(fields) {
  return fields.map((field) => ({
    name: field.name.trim(), type: field.type || "string", description: field.description || "",
    fields: isNested(field) ? serializeFields(field.fields || []) : [],
  }));
}
