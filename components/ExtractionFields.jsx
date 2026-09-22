"use client";

import { Plus, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { FIELD_TYPES, isNested, newField } from "@/lib/extraction-fields";

export default function ExtractionFields({ fields, onChange, depth = 1, path = "" }) {
  const update = (index, changes) => onChange(fields.map((field, i) => i === index ? { ...field, ...changes } : field));
  return <div className="extraction-tree">
    <div className="fields-intro"><span>{depth === 1 ? "Поля результата" : "Вложенные поля"}</span><Button variant="outline" size="sm" onClick={() => onChange([...fields, newField()])}><Plus size={15}/>Добавить поле</Button></div>
    <div className="fields-list">{fields.map((field, index) => {
      const label = `${path}${index + 1}`;
      return <div className="typed-field-card" key={index}>
        <div className="typed-field-heading"><span className="field-number">{label}</span><Input aria-label={`Название поля ${label}`} value={field.name} onChange={(event) => update(index, { name: event.target.value })} placeholder="Название поля, например total"/>
          <select className="field-type-select" aria-label={`Тип поля ${label}`} value={field.type || "string"} onChange={(event) => update(index, { type: event.target.value, fields: ["array", "object"].includes(event.target.value) ? field.fields || [] : [] })}>
            {FIELD_TYPES.map(([value, title]) => <option key={value} value={value} disabled={depth >= 6 && ["object", "array"].includes(value)}>{title}</option>)}
          </select><Button variant="ghost" size="icon" aria-label={`Удалить поле ${label}`} onClick={() => onChange(fields.filter((_, i) => i !== index))}><Trash2 size={16}/></Button>
        </div>
        <details className="field-instructions" open={field.description ? true : undefined}><summary>Инструкции извлечения — только для модели</summary><Textarea aria-label={`Инструкции поля ${label}`} rows={2} value={field.description || ""} onChange={(event) => update(index, { description: event.target.value })} placeholder="Правила поиска и обработки значения"/></details>
        {isNested(field) && <div className="nested-fields"><p>{field.type === "array" ? "Каждый элемент списка — объект с указанными ниже полями." : "Состав объекта."}</p><ExtractionFields fields={field.fields || []} onChange={(children) => update(index, { fields: children })} depth={depth + 1} path={`${label}.`}/></div>}
      </div>;
    })}</div>
    {fields.length === 0 && <p className="field-tree-hint">Добавьте хотя бы одно поле.</p>}
    {depth === 1 && <p className="field-tree-hint">Названия полей должны быть уникальными внутри объекта. Если значение не найдено, API вернёт null. Максимум 6 уровней вложенности.</p>}
  </div>;
}
