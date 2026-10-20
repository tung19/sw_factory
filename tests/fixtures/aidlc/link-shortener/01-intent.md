# Intent — Link Shortener

## Problem
People share long URLs that are awkward to paste and track. We want a minimal
service that turns a long URL into a short code and redirects visitors.

## Goals
- Turn any valid URL into a short, unique code.
- Redirect a short code to its original URL.
- Count how many times each short link was visited.

## Constraints
- Single service, no accounts (anonymous).
- A short code is 6 URL-safe characters.
- Durable: links and their counts survive a restart.

## Data model
- **Link**: `code` (string, required), `url` (string, required), `visits` (int, required), `createdAt` (datetime, required)
