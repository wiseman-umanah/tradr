# Tradr

Tradr is a Textual-based terminal trading desk built by **Wiseman Umanah**. It combines a live ASCII candlestick chart, an AI-powered chat console, and a continuously updating watchlist sourced from Yahoo Finance screeners.

## Features

- **Live chart**: Plotext candlesticks that refresh automatically and follow the app's light/dark theme.
- **AI + commands**: A chat console where quick commands (`chart`, `watch`, `analyze`, `set-key`, `about`, etc.) coexist with a Groq-backed assistant.
- **Dynamic watchlist**: Dozens of trending tickers, rotating through a cached universe, with keyboard focus + scrolling.


## Getting Started

### Linux/macOS via install script

```bash
curl -fsSL https://raw.githubusercontent.com/wiseman-umanah/tradr/refs/heads/master/install.sh | bash
```

The script installs dependencies with `uv`, sets up entry points, and guides you through launching `tradr-dev`.

### Windows / manual install

```bash
pip install tradr
# or, for development:
uv sync
uv run tradr
```

Set `GROQ_API_KEY="gsk_..."` (or run `set-key <gsk_...>` inside the app), press `d` to toggle the theme, type `help` to see every command, and run `about` to view author details.

## About the Author

Created by **Wiseman Umanah** ([@wiseman-umanah](https://github.com/wiseman-umanah)). Feel free to reach out for feedback, collaborations, or feature ideas.
