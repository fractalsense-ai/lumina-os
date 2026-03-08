# Front-End Setup (Project Lumina)

This folder contains a Vite + React + TypeScript app that talks to the Lumina API.

## Prerequisites

- Node.js 18+
- npm
- Lumina API server running on `http://localhost:8000` (default)

## Install

Use one of these commands in PowerShell:

```powershell
npm.cmd install
```

If your shell allows `npm` directly, this also works:

```powershell
npm install
```

## Run

```powershell
npm.cmd run dev
```

## Build

```powershell
npm.cmd run build
```

## Optional API base override

Set `VITE_LUMINA_API_BASE_URL` if your API is not at `http://localhost:8000`:

```powershell
$env:VITE_LUMINA_API_BASE_URL = "http://127.0.0.1:8000"
npm.cmd run dev
```

## Troubleshooting

- PowerShell error: `npm.ps1 cannot be loaded`
: Use `npm.cmd ...` commands, or run a process-scoped execution policy bypass.
- TypeScript errors about `Set`, `Map`, `Iterable`, `node:*`
: Ensure dependencies are installed (`npm.cmd install`) and build with current config files.
