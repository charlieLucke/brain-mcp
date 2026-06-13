# Architektur

> Design auf Systemebene. Aktualisieren, wenn sich Module, Contracts oder Datenmodelle ändern.

## Überblick
*(Ein Absatz: Was macht dieses Projekt auf Systemebene?)*

## Modulübersicht
*(High-Level-Module und ihre Verantwortlichkeiten. Beispiel unten.)*

```
src/brain_mcp/
├── api/          # HTTP-/CLI-Schnittstellenschicht
├── core/         # Domänenlogik
├── adapters/     # Clients für externe Services (DB, APIs)
├── config/       # Konfigurations-Laden
└── main.py       # Einstiegspunkt
```

## Datenmodell
*(Schlüssel-Entitäten und ihre Beziehungen. ERD oder Prosa.)*

## Externe Services
*(APIs, Datenbanken, Message-Queues, Datei-Storage usw. Jeweils mit Zweck auflisten.)*

## Datenfluss
*(Wie bewegen sich Daten durch das System? End-to-end für den Hauptanwendungsfall.)*

## Deployment
*(Wo und wie das läuft. Lokal, Cloud, Container, Serverless.)*
