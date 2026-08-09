# Linked label catalogs

JSON files in this directory are discovered automatically. Each file uses
schema version 1 and contains a `labels` array. A label can reference a stable
symbol ID and variant:

```json
{
  "schema_version": 1,
  "labels": [
    {
      "id": "gnd",
      "text": "GND",
      "category": "Power",
      "symbol_id": "builtin.ground",
      "symbol_variant": "default"
    }
  ]
}
```

Label IDs must be unique across every file in this directory.
