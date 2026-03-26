# Agent Instructions for Gestione Consegne

This document provides guidelines for agentic coding assistants working on this repository.

## Project Overview

Gestione Consegne is a delivery management system with:
- Python backend (server.py) - HTTP server, data persistence, business logic
- HTML/CSS/JS frontend (index.html) - Responsive UI with dark/light themes
- PowerShell/Batch scripts for startup and firewall configuration
- JSON-based data storage with automatic backups
- Enhanced delivery status tracking with backward compatibility

## Build/Lint/Test Commands

### Python Backend
```bash
# Run the server locally
python server.py

# Check for syntax errors
python -m py_compile server.py

# Run with embedded Python (if available)
.\python_embed\python.exe server.py
```

### Frontend
```bash
# No build step required - static files only
# Serve locally for development:
python -m http.server 8000
```

### Code Quality
```bash
# Check Python syntax
python -m py_compile server.py

# No specific linter configured - follow PEP 8
```

## Code Style Guidelines

### Python (server.py)

#### Imports
- Place all imports at the top of the file
- Standard library imports first, then third-party
- Use explicit imports (no `import *`)
- Group imports logically

#### Formatting
- Follow PEP 8 style guide
- Use 4 spaces for indentation (no tabs)
- Line length: 100 characters maximum
- Use double quotes for strings
- No trailing whitespace

#### Naming Conventions
- Variables: `snake_case`
- Functions: `snake_case`
- Classes: `PascalCase`
- Constants: `UPPER_SNAKE_CASE`
- Private members: prefixed with `_`

#### Types and Documentation
- Use type hints where possible
- Document functions with docstrings for complex logic
- Keep functions focused and small
- Use meaningful variable names

#### Error Handling
- Handle exceptions close to where they occur
- Log errors with appropriate level (error, critical)
- Gracefully handle file I/O errors
- Use specific exception types when possible

#### Structure
- Group related functions together
- Separate concerns (data I/O, HTTP handling, business logic)
- Use helper functions to avoid code duplication
- Keep global state minimal

### HTML/CSS/JavaScript (index.html)

#### HTML Structure
- Use semantic HTML elements
- Maintain proper indentation (2 spaces)
- Attribute values in double quotes
- Logical section organization with comments

#### CSS
- Use CSS variables for consistent theming
- Mobile-first responsive design
- Utility classes for common patterns
- Scoped styles (no global pollution)
- Organize styles by component sections

#### JavaScript
- Use `const` and `let` instead of `var`
- Prefer arrow functions for callbacks
- Modular code organization
- Event delegation for dynamic elements
- Consistent naming: `camelCase` for variables/functions
- Comment complex logic

#### Frontend Architecture
- Single-page application with view switching
- State management in global `db` object
- Automatic data synchronization
- Client-side rendering

## Testing

### Manual Testing
```bash
# 1. Start the server
python server.py

# 2. Open browser to http://localhost:8742

# 3. Test core functionality:
# - Add/edit/delete deliveries
# - Create/organize delivery days
# - Team management
# - Theme switching
# - Multi-user scenarios
```

### Testing Individual Components
```bash
# Test server API directly
curl http://localhost:8742/api/ping
curl http://localhost:8742/api/data

# Test data persistence
# Check dati.json and backup/ directory
```

## Development Workflow

1. Always read existing code to understand patterns
2. Follow existing code style and conventions
3. Test changes manually before committing
4. Keep commits focused on single concerns
5. Write clear, descriptive commit messages

## Common Patterns in Codebase

### Server Patterns
- Data read/write with automatic backup
- HTTP API with JSON responses
- Client tracking and heartbeat
- Error logging and crash handling
- System tray integration (Windows)

### Frontend Patterns
- View-based navigation
- Modal dialogs for forms
- Drag-and-drop reordering
- Real-time synchronization
- Theme-aware styling
- Form validation and character counters

## Dependencies

### Required
- Python 3.8+
- pystray (for system tray icon)
- Pillow (for system tray icon generation)

### Optional
- PowerShell (Windows) for startup scripts
- Browser with modern JavaScript support

## File Structure
```
gestione_consegne/
├── server.py          # Main server logic
├── index.html         # Frontend UI
├── avvia.bat/ps1      # Startup scripts
├── configura_firewall.bat  # Firewall setup
├── dati.json          # Main data file
├── backup/            # Automatic backups
├── python_embed/      # Embedded Python (if used)
└── README.md          # Project documentation
```

## Agent-Specific Guidelines

1. When editing HTML/CSS:
   - Maintain the dark/light theme support
   - Respect existing color palette and variables
   - Keep responsive design intact

2. When editing Python:
   - Preserve server reliability features
   - Maintain data integrity mechanisms
   - Keep network synchronization working

3. When adding features:
   - Follow existing UI patterns
   - Maintain multi-user compatibility
   - Add appropriate logging
   - Consider backup/data safety

4. Security considerations:
   - No external network access
   - Local network only operation
   - Data file protection
   - Input validation on all forms