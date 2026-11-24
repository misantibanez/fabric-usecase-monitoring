"""Generate PBIR report parts bound to the independent monitoring model."""
import argparse
import json
from datetime import date
from pathlib import Path


BASE = "https://developer.microsoft.com/json-schemas/fabric/item/report/"


def field(table: str, name: str, measure: bool = False) -> dict:
    return {"Measure" if measure else "Column": {
        "Expression": {"SourceRef": {"Entity": table}}, "Property": name,
    }}


def build_report(model_id: str, focus_date: str, daily: bool = False) -> dict[str, str]:
    date.fromisoformat(focus_date)
    objects: dict[str, dict] = {
        "definition.pbir": {
            "$schema": BASE + "definitionProperties/2.0.0/schema.json",
            "version": "4.0",
            "datasetReference": {"byConnection": {"connectionString": "semanticmodelid=" + model_id}},
        },
        "definition/version.json": {
            "$schema": BASE + "definition/versionMetadata/1.0.0/schema.json", "version": "2.0.0",
        },
        "definition/report.json": {
            "$schema": BASE + "definition/report/3.1.0/schema.json",
            "themeCollection": {"baseTheme": {
                "name": "CY25SU12", "type": "SharedResources",
                "reportVersionAtImport": {"visual": "2.0.0", "report": "3.1.0", "page": "2.0.0"},
            }},
            "settings": {"useStylableVisualContainerHeader": True, "useEnhancedTooltips": True},
        },
        "definition/pages/pages.json": {
            "$schema": BASE + "definition/pagesMetadata/1.0.0/schema.json",
            "pageOrder": ["Estimated", "Demo", "Inventory", "Assumptions"],
            "activePageName": "Estimated",
        },
    }

    def page(name: str, title: str, default_date: bool = False) -> None:
        value = {
            "$schema": BASE + "definition/page/2.0.0/schema.json",
            "name": name, "displayName": title, "displayOption": "FitToPage",
            "height": 900, "width": 1440,
        }
        if default_date:
            value["filterConfig"] = {"filters": [{
                "name": "ReportDay", "field": field("Date", "Report Date"),
                "type": "Categorical", "howCreated": "User",
                "filter": {"Version": 2, "From": [{"Name": "d", "Entity": "Date", "Type": 0}],
                    "Where": [{"Condition": {"In": {
                        "Expressions": [{"Column": {"Expression": {"SourceRef": {"Source": "d"}}, "Property": "Report Date"}}],
                        "Values": [[{"Literal": {"Value": "datetime'" + focus_date + "T00:00:00'"}}]],
                    }}}]},
            }]}
            if daily:
                rule = value["filterConfig"]["filters"][0]
                rule["name"] = "Rolling30Days"
                rule["field"] = field("Date", "In Rolling Window")
                condition = rule["filter"]["Where"][0]["Condition"]["In"]
                condition["Expressions"][0]["Column"]["Property"] = "In Rolling Window"
                condition["Values"] = [[{"Literal": {"Value": "1L"}}]]
        objects[f"definition/pages/{name}/page.json"] = value

    def visual(page_name: str, name: str, visual_type: str, title: str,
               x: int, y: int, width: int, height: int,
               roles: dict[str, list[tuple[str, str, bool]]]) -> None:
        query = {}
        for role, fields in roles.items():
            query[role] = {"projections": [{
                "field": field(table, column, is_measure),
                "queryRef": f"{table}.{column}", "nativeQueryRef": column,
            } for table, column, is_measure in fields]}
        objects[f"definition/pages/{page_name}/visuals/{name}/visual.json"] = {
            "$schema": BASE + "definition/visualContainer/2.0.0/schema.json",
            "name": name, "position": {"x": x, "y": y, "z": len(objects),
                "width": width, "height": height, "tabOrder": len(objects)},
            "visual": {
                "visualType": visual_type, "query": {"queryState": query},
                "drillFilterOtherVisuals": True,
                "visualContainerObjects": {"title": [{"properties": {
                    "show": {"expr": {"Literal": {"Value": "true"}}},
                    "text": {"expr": {"Literal": {"Value": "'" + title.replace("'", "''") + "'"}}},
                }}]},
            },
        }

    def warning(page_name: str, demo: bool = False) -> None:
        visual(page_name, page_name + "Warning", "card", "Advertencia de uso", 20, 10, 1400, 80,
               {"Values": [("Demo" if demo else "Consumption", "Demo Warning" if demo else "Not For Billing", True)]})

    page("Estimated", "01 Consumo estimado - NO APTO PARA COBRO", True)
    warning("Estimated")
    cards = [
        ("CU-segundos reales", "Consumption", "Observed CU Seconds"),
        ("CU-segundos disponibles asumidos", "Availability", "Assumed Available CU Seconds"),
        ("% capacidad estimado", "Consumption", "Estimated Capacity Usage"),
        ("Dias/capacidad sin supuestos", "Availability", "Missing Availability Days"),
    ]
    if daily:
        cards.append(("Dias/capacidad sin datos fuente", "Availability", "Missing Source Days"))
    card_width = 1400 // len(cards)
    for index, (title, table, measure) in enumerate(cards):
        visual("Estimated", "EstimatedCard" + str(index), "card", title, 20 + card_width * index, 105, card_width - 15, 120,
               {"Values": [(table, measure, True)]})
    for index, (table, column) in enumerate([
        ("Capacity", "Capacity"), ("Classification", "Use Case"),
        ("Classification", "Domain"), ("Classification", "Subdomain"),
    ]):
        visual("Estimated", "EstimatedFilter" + str(index), "slicer", column, 20 + index * 350, 240, 335, 110,
               {"Values": [(table, column, False)]})
    visual("Estimated", "CaseUsage", "barChart", "% de capacidad por caso de uso (estimado)", 20, 365, 680, 285,
           {"Category": [("Classification", "Use Case", False)],
            "Y": [("Consumption", "Estimated Capacity Usage", True)]})
    visual("Estimated", "HierarchyConsumption", "tableEx", "Resumen por caso - filtrar dominio/subdominio arriba", 720, 365, 700, 510,
           {"Values": [
               ("Classification", "Use Case", False),
               ("Consumption", "Observed CU Seconds", True), ("Consumption", "Estimated Capacity Usage", True),
               ("Classification", "Classification Status", False),
           ]})
    visual("Estimated", "SelectedDate", "slicer", "Dia del reporte (cambiar filtro ReportDay en panel Filtros)", 20, 665, 680, 115,
           {"Values": [("Date", "Report Date", False)]})
    if daily:
        objects["definition/pages/Estimated/visuals/SelectedDate/visual.json"]["visual"]["visualContainerObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"] = "'Ultimos 30 dias completos al ultimo procesamiento; filtrar fechas dentro del rango'"
    visual("Estimated", "RefreshTimestamp", "tableEx", "Ultima importacion UTC", 20, 795, 680, 80,
           {"Values": [("Refresh", "Refresh UTC", False)]})

    page("Demo", "02 Demo sintetica - NO APTO PARA COBRO")
    warning("Demo", True)
    visual("Demo", "DemoFilter", "slicer", "Escenario sintetico", 20, 105, 400, 160,
           {"Values": [("Demo", "Scenario", False)]})
    visual("Demo", "DemoResults", "tableEx", "Resultados sinteticos: cero, >100%, pausa, SKU y datos faltantes", 20, 280, 1400, 595,
           {"Values": [
               ("Demo", "Scenario", False), ("Demo", "Use Case", False), ("Demo", "Status", False),
               ("Demo", "Demo CU Seconds", True), ("Demo", "Demo Available CU Seconds", True),
               ("Demo", "Demo Capacity Usage", True),
           ]})
    visual("Demo", "DemoChart", "barChart", "% sintetico por escenario", 440, 105, 980, 160,
           {"Category": [("Demo", "Scenario", False)], "Y": [("Demo", "Demo Capacity Usage", True)]})

    page("Inventory", "03 Objetos - clasificacion actual")
    warning("Inventory")
    visual("Inventory", "InventoryCount", "card", "Objetos capturados (no solo objetos con consumo)", 20, 105, 400, 120,
           {"Values": [("Inventory", "Inventory Items", True)]})
    for index, (table, column) in enumerate([
        ("Classification", "Use Case"), ("Inventory", "Item Type"), ("Capacity", "Capacity"),
    ]):
        visual("Inventory", "InventoryFilter" + str(index), "slicer", column, 440 + index * 330, 105, 310, 120,
               {"Values": [(table, column, False)]})
    visual("Inventory", "InventoryRows", "tableEx", "Herencia del workspace; incluye sin consumo y marcados eliminados", 20, 240, 1400, 635,
           {"Values": [
               ("Classification", "Domain", False), ("Classification", "Subdomain", False),
               ("Classification", "Use Case", False), ("Inventory", "Workspace", False),
               ("Inventory", "Item", False), ("Inventory", "Item Type", False),
               ("Inventory", "Item State", False), ("Inventory", "Marked Deleted", False),
               ("Classification", "Classification Status", False),
               ("Inventory", "Inventory Items", True),
           ]})

    page("Assumptions", "04 Supuestos y cobertura")
    warning("Assumptions")
    visual("Assumptions", "AssumptionsDays", "tableEx", "Disponibilidad asumida por capacidad/dia; null no significa cero", 20, 105, 1400, 770,
           {"Values": [
               ("Capacity", "Capacity", False), ("Date", "Report Date", False),
               ("Availability", "Estimate Status", False), ("Availability", "Assumptions", False),
               ("Availability", "Source Offset Minutes", False),
               ("Availability", "UTC Start", False), ("Availability", "UTC End", False),
               ("Availability", "Assumed Available CU Seconds", True),
               ("Availability", "Missing Availability Days", True),
           ]})
    if daily:
        visual("Assumptions", "DailyCoverage", "tableEx", "Cobertura FUAM por dia; filas presentes no certifican integridad", 20, 105, 1400, 340,
               {"Values": [
                   ("Capacity", "Capacity", False), ("Date", "Report Date", False),
                   ("Availability", "Source Coverage", False),
                   ("Availability", "Last Source Check UTC", False),
                   ("Availability", "Missing Source Days", True),
                   ("Availability", "Source Days With Rows", True),
               ]})
        position = objects["definition/pages/Assumptions/visuals/AssumptionsDays/visual.json"]["position"]
        position.update(y=460, height=415)
    return {path: json.dumps(value, ensure_ascii=True) for path, value in objects.items()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--focus-date", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    Path(args.output).write_text(json.dumps(build_report(args.model_id, args.focus_date)), encoding="utf-8")
