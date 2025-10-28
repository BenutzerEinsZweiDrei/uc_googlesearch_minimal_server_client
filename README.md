# Google Search Scraper - Minimal Server/Client

Minimal setup with server and client for Google search, featuring a standalone scraper with full headless mode support.

## Features

- **Standalone Scraper**: `scrape_google.py` - Direct Google search scraping
- **Headless Mode**: Fully functional headless Chrome support
- **Undetected ChromeDriver**: Uses undetected-chromedriver to bypass bot detection
- **Server/Client**: Distributed scraping via `server.py` and `client.py`

## Installation

```bash
pip install setuptools undetected-chromedriver selenium beautifulsoup4
```

## Quick Start

### Standalone Scraper

```bash
# Basic search in headless mode
python scrape_google.py --query "python tutorial" --headless --max 5

# Non-headless mode (requires display)
python scrape_google.py --query "python tutorial" --max 5

# With debug logging
python scrape_google.py --query "python tutorial" --headless --debug

# Different language
python scrape_google.py --query "python tutorial" --headless --lang de-DE
```

### Programmatic Usage

```python
from scrape_google import SimpleGoogleScraper

# Create scraper in headless mode
scraper = SimpleGoogleScraper(headless=True, timeout=10, lang="en-US")

try:
    scraper.start()
    results = scraper.search("python tutorial", max_results=5)
    
    for result in results:
        print(f"{result.rank}. {result.title}")
        print(f"   {result.url}")
finally:
    scraper.stop()
```

## Headless Mode

The scraper now fully supports headless mode with proper configuration:

✅ **Working Features:**
- Automatic driver path management (copies to writable location)
- Modern headless mode (`--headless=new`)
- Optimized Chrome options for headless rendering
- Proper resource cleanup
- Comprehensive logging and error handling

### Key Improvements

1. **Driver Path Management**: Automatically copies system chromedriver to a writable temporary location
2. **Enhanced Chrome Options**: 10+ headless-specific options for reliable operation
3. **Better Error Handling**: Detailed logging with `--debug` flag
4. **Resource Cleanup**: Automatic cleanup of temporary files

## Command Line Options

```
--query, -q    Search query (required)
--headless     Run in headless mode
--max          Maximum number of results (default: 10)
--lang         Language preference (default: en-US)
--debug        Enable debug logging
```

## Files

- `scrape_google.py` - Standalone scraper with headless support
- `server.py` - Server component for distributed scraping
- `client.py` - Client component for distributed scraping

## Requirements

- Python 3.7+
- Chrome/Chromium 96+ (for modern headless mode)
- undetected-chromedriver
- selenium
- beautifulsoup4

## Notes

- Headless mode is recommended for automated/server environments
- Non-headless mode requires a display (X11/Wayland)
- First run may download chromedriver if not found locally
