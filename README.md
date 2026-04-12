# Tradr

Tradr is a Textual-based terminal trading desk built by **Wiseman Umanah**. It combines a live ASCII candlestick chart, an AI-powered chat console, and a continuously updating watchlist sourced from Yahoo Finance screeners.

## Features

- **Live chart**: Plotext candlesticks that refresh automatically and follow the app's light/dark theme.
- **AI + commands**: A chat console where quick commands (`chart`, `watch`, `analyze`, `set-key`, `about`, etc.) coexist with a Groq-backed assistant.
- **Dynamic watchlist**: Dozens of trending tickers, rotating through a cached universe, with keyboard focus + scrolling.
- **Branding everywhere**: Header/footer and the `about` command keep the author's signature front and center.

## Getting Started

```bash
uv sync
run `set-key <gsk_...>` in the app
uv run tradr-dev
```

Press `d` to toggle the theme, type `help` to see every command, and run `about` to view author details.

## About the Author

Created by **Wiseman Umanah** ([@wiseman-umanah](https://github.com/wiseman-umanah)). Feel free to reach out for feedback, collaborations, or feature ideas.
