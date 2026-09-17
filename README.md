# COPA

> A lightweight desktop copilot for weighing equipment selection, quotation, and technical documentation.

COPA is a desktop application driven by **deterministic selection rules, reusable workflows**, and product data.

Instead of manually looking up data, calculating results, and preparing documents, COPA reconstructs these steps into a new workflow:

```text
Requirement
    ↓
Selection
    ↓
Project Snapshot  →  Technical Documentation
    ↓
Quotation

(and more, someday)
```

## Key Features

* **Rule-based selection** — deterministic and inspectable business logic
* **Human-in-the-loop** — software proposes; humans review and confirm
* **Project snapshots** — readable and reusable structured/AI-friendly data for downstream workflows
* **Technical documentation** — generate proposals from project data
* **Configurable data** — product data, rules, and templates are loaded and maintained separately

## Tech Stack

* Python
* PySide6
* OpenPyXL
* PyInstaller
* CSV / structured data
* Microsoft Word document generation

## Development

COPA originated from actual weighing-equipment quotation workflows.

It was developed through **business-rule analysis, iterative prototyping, testing, and AI-assisted coding**, without a traditional software-engineering background.

The core principle is simple:

> **If a messy real-world workflow can be taught to another human in rules and data, it can also be turned into a working automated tool.**

## Current Release

**v1.31 External**

This repository contains a sanitized public version for demonstration and portfolio purposes.

---

**Author:** Hero Pang
