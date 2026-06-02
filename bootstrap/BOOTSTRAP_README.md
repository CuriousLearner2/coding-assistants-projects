# Project Bootstrap System

Create production-ready projects in minutes with built-in best practices, safety mechanisms, and learning systems.

## Quick Start: Create a New Project

```bash
cd "/Users/gautambiswas/Claude Code"
python project_bootstrap.py
```

Then answer 4 questions:

1. **Project path** — Where to create it (e.g., `~/projects/my-app`)
2. **Project name** — What to call it (auto-filled from path)
3. **Domain/Tech** — What you're building (e.g., `Python Web API`, `Browser Automation`)
4. **Description** — Brief overview (e.g., `Real estate listing parser`)
5. **Confirm** — Type `y` to create

Done! The script will:
- ✅ Create project directory with structure
- ✅ Generate all template files
- ✅ Initialize git repository
- ✅ Install pre-commit hook
- ✅ Create initial commit

**Total time: 2 minutes**

---

## What You Get

### Complete Directory Structure

```
your-project/
├── .git/hooks/pre-commit           ← Automated safety
├── .github/CHECKLIST.md            ← Pre-submission checklist
├── src/                            ← Your code
├── tests/unit/                     ← Unit tests
├── tests/integration/              ← Integration tests
├── scripts/                        ← Helper scripts
├── docs/                           ← Documentation
│
├── CLAUDE.md                       ← ⭐ READ FIRST
├── SKILL_[DOMAIN].md               ← ⭐ Best practices
├── TESTING_GUIDE.md                ← Testing patterns
├── README.md                       ← Project overview
├── PREVENTION.md                   ← Automation guide
├── .env.example                    ← Environment template
├── .gitignore                      ← Git configuration
└── requirements.txt                ← Python dependencies
```

### 10 Essential Files Generated

| File | Purpose | Read When |
|------|---------|-----------|
| **CLAUDE.md** | Critical requirements, workflow, troubleshooting | Starting work, debugging |
| **SKILL_[DOMAIN].md** | Best practices & patterns for your domain | Writing code |
| **TESTING_GUIDE.md** | How to write and run tests | Creating tests |
| **README.md** | Quick start and project overview | First time setup |
| **.github/CHECKLIST.md** | Pre-submission verification | Before committing |
| **PREVENTION.md** | Automation & safety mechanisms | Understanding hooks |
| **.env.example** | Environment variable template | Setup |
| **.gitignore** | What git should ignore | Git configuration |
| **requirements.txt** | Python dependencies | Environment setup |
| **.git/hooks/pre-commit** | Automated rule enforcement | Understanding automation |

---

## File Details

### CLAUDE.md — Your Project Guidelines

Contains everything for working on the project:

```markdown
# Project: [Your Project]

## Critical Requirements

### Requirement 1: Code Quality
**NEVER:** Commit without testing
**ALWAYS:** Run tests before committing

### Requirement 2: Documentation
**NEVER:** Commit undocumented changes
**ALWAYS:** Explain the "why" in comments

## Workflow
- Setup: Create venv, install dependencies
- Development: Create branch, code, test
- Committing: Hook validates, prevents mistakes

## Testing
- Unit tests: pytest tests/unit/
- Integration: pytest tests/integration/
- Full suite: pytest

## Problem Solving
[Issue] → [Root cause] → [Solution] → [Prevention]
```

**Use this:** Reference for "can I do this?" and "how?"

### SKILL_[DOMAIN].md — Best Practices

Shows the right way to build in your domain:

```markdown
# SKILL: Best Practices for [DOMAIN]

## Core Concepts
[Key patterns with examples]

## Common Patterns
[Successful approaches with code]

## Anti-Patterns
[What not to do and why]

## Testing Strategy
[How to test in this domain]

## Troubleshooting
[Common problems and solutions]
```

**Use this:** When coding, designing, or debugging

### TESTING_GUIDE.md — Test Patterns

Shows how to organize and write tests:

```markdown
# Testing Guide

## Organization
tests/
├── unit/          - Fast, isolated
├── integration/   - Cross-component
└── conftest.py    - Shared fixtures

## Running Tests
pytest              # All
pytest tests/unit/  # Specific
pytest -v          # Verbose
pytest --cov       # Coverage

## Template
def test_feature_does_something():
    # Arrange - setup
    # Act - execute
    # Assert - verify

## Best Practices
- One assertion per test
- Clear test names
- Use fixtures
- Mock external APIs
```

**Use this:** When writing tests

### README.md — Project Overview

Quick start guide for the project:

```markdown
# [Project Name]

[Description]

## Quick Start

Prerequisites: Python 3.8+

Setup:
git clone ...
cd project
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest

## Development
See CLAUDE.md for guidelines
See SKILL_[DOMAIN].md for patterns
See TESTING_GUIDE.md for tests
```

**Use this:** First-time setup

### .github/CHECKLIST.md — Pre-Submission

Verify before committing:

```markdown
# Pre-Submission Checklist

Code Quality:
- [ ] No linter errors
- [ ] All tests pass
- [ ] No hardcoded secrets
- [ ] Clear variable names

Testing:
- [ ] New code has tests
- [ ] Existing tests pass
- [ ] Happy path + errors covered

Documentation:
- [ ] Comments explain "why"
- [ ] Function docstrings present
- [ ] Updated CLAUDE.md if needed
- [ ] Updated README if needed

Final Review:
- [ ] Tested locally
- [ ] Read CLAUDE.md requirements
- [ ] Reviewed SKILL_[DOMAIN].md
- [ ] Production-ready

Don't commit if any unchecked!
```

**Use this:** Before every commit

### PREVENTION.md — Automation

Explains what's automatically blocked:

```markdown
# Prevention Mechanisms

## What Gets Blocked

Pre-commit Hook:
- Hardcoded secrets
- Large files (>10MB)
- Python syntax errors
- [Project-specific patterns]

## If Hook Blocks

1. Read error message
2. Check CLAUDE.md Critical Requirements
3. Fix the issue
4. Try committing again

Bypass (emergency only):
git commit --no-verify
```

**Use this:** Understanding automation

### Other Files

- **.env.example** — Copy to `.env` and fill in your values
- **.gitignore** — Already configured for Python, IDE, testing, secrets
- **requirements.txt** — Core dependencies (pytest) with placeholders
- **tests/conftest.py** — For shared test fixtures
- **src/__init__.py** — Makes `src` a Python package

---

## After Generation: Next Steps

### 1. Navigate to Project

```bash
cd /path/to/your/project
```

### 2. Read Documentation (30 minutes)

```bash
cat README.md                    # 2 min - overview
cat CLAUDE.md                    # 10 min - guidelines
cat SKILL_[DOMAIN].md            # 15 min - best practices
cat TESTING_GUIDE.md             # 3 min - testing
```

### 3. Set Up Environment

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pytest --collect-only            # Verify tests discovered
```

### 4. Start Coding

```bash
# Create feature branch
git checkout -b feature/your-feature

# Write code in src/
# Write tests in tests/unit/ or tests/integration/

# Before committing, check:
cat .github/CHECKLIST.md

# Commit
git commit -m "feat: Your feature"
# Pre-commit hook runs automatically
# If it passes, commit succeeds
```

### 5. When Something Goes Wrong

```bash
# Tests failing?
cat TESTING_GUIDE.md
pytest -v

# Unsure if code is right?
cat SKILL_[DOMAIN].md

# Hook blocking commit?
cat PREVENTION.md
cat CLAUDE.md
```

---

## Complete Example Workflow

### Step 1: Create Project

```bash
cd "/Users/gautambiswas/Claude Code"
python project_bootstrap.py

# Prompts:
# Project path: ~/projects/real-estate-parser
# Project name: real-estate-parser
# Domain: Python Data Pipeline
# Description: Extract and enrich real estate listings
# Confirm: y
```

### Step 2: See Output

```
============================================================
✅ Project Created Successfully!
============================================================

📂 Location: /Users/gautambiswas/projects/real-estate-parser

📖 Next Steps:
   1. cd /Users/gautambiswas/projects/real-estate-parser
   2. Read CLAUDE.md (critical requirements)
   3. Read SKILL_PYTHON_DATA_PIPELINE.md (best practices)
   4. Create virtual environment: python -m venv venv
   5. Activate: source venv/bin/activate
   6. Install: pip install -r requirements.txt
   7. Start coding!

💡 Key Documents:
   • CLAUDE.md - Project guidelines
   • SKILL_PYTHON_DATA_PIPELINE.md - Best practices
   • TESTING_GUIDE.md - Testing patterns
   • .github/CHECKLIST.md - Pre-submission checklist

============================================================
```

### Step 3: Follow the Steps

```bash
cd ~/projects/real-estate-parser
cat README.md        # 2 min
cat CLAUDE.md        # 10 min  
cat SKILL_PYTHON_DATA_PIPELINE.md  # 15 min
cat TESTING_GUIDE.md # 3 min
# Now you understand the project!

python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Step 4: Start Developing

```bash
# Create feature branch
git checkout -b feature/parse-listings

# Write code in src/parse_listings.py
# Write tests in tests/unit/test_parse_listings.py

# Test
pytest

# Check checklist before committing
cat .github/CHECKLIST.md
# Verify: code quality ✓, tests pass ✓, no secrets ✓

# Commit
git commit -m "feat: Add listing parser"
# Pre-commit hook runs and validates
# Commit succeeds!
```

---

## Customization

After bootstrap creates the project, customize it:

### Add Critical Requirement to CLAUDE.md

```markdown
### Requirement 3: No Hardcoded Secrets

**NEVER:**
database_url = "postgres://user:password@localhost/db"

**ALWAYS:**
database_url = os.getenv("DATABASE_URL")

**Why it matters:**
- Prevents credential leaks
- Enables different configs per environment
```

### Add Patterns to SKILL_[DOMAIN].md

Add real examples from your codebase:

```markdown
### Pattern: Async Data Processing

**When to use:** Processing large datasets

**Implementation:**
[Code from your actual project]

**Pros/Cons:**
- Pro: Scales to large files
- Con: Slightly more complex
```

### Customize Pre-commit Hook

Add project-specific pattern blocking to `.git/hooks/pre-commit`:

```bash
# Block hardcoded database URLs
if git diff --cached | grep -q 'postgres://'; then
    echo "❌ Error: Hardcoded database URL detected"
    exit 1
fi
```

### Fill in .env.example

```bash
# .env.example
DATABASE_URL=postgres://localhost/mydb
API_KEY=your-api-key-here
DEBUG=False
LOG_LEVEL=INFO
SECRET_KEY=change-me-in-production
```

---

## Key Features

### ✅ Pre-Configured Everything

- Directory structure ready to use
- Git repository initialized
- Pre-commit hook installed
- Test structure created
- Dependencies listed

### ✅ Critical Requirements Clear

- CLAUDE.md lists "NEVER" and "ALWAYS"
- Everyone knows standards
- No ambiguity

### ✅ Domain-Specific Knowledge

- SKILL_[DOMAIN].md customized for your tech
- Real code examples (right vs wrong)
- Patterns, anti-patterns, testing strategies
- Troubleshooting built in

### ✅ Automated Safety

- Pre-commit hook blocks secrets
- Prevents large files in git
- Validates Python syntax
- Customizable for project patterns

### ✅ Testing Ready

- Test structure created
- Pytest configured
- Testing guide included
- Unit vs integration organized

### ✅30-Minute Onboarding

Read 5 documents, understand everything:
1. README.md (2 min)
2. CLAUDE.md (10 min)
3. SKILL_[DOMAIN].md (15 min)
4. TESTING_GUIDE.md (3 min)
5. CHECKLIST.md (3 min)

Now you know:
- ✓ Project requirements
- ✓ Best practices
- ✓ How to test
- ✓ What to avoid
- ✓ How to commit

---

## Troubleshooting

### Script won't run

```bash
# Make executable
chmod +x "/Users/gautambiswas/Claude Code/project_bootstrap.py"

# Run with python
python "/Users/gautambiswas/Claude Code/project_bootstrap.py"
```

### Pre-commit hook not working

```bash
cd your-project

# Make executable
chmod +x .git/hooks/pre-commit

# Test it
.git/hooks/pre-commit

# If syntax error:
bash -x .git/hooks/pre-commit
```

### Path issues on macOS

Use full path:
```bash
python "/Users/gautambiswas/Claude Code/project_bootstrap.py"
```

Or create alias:
```bash
alias bootstrap='python "/Users/gautambiswas/Claude Code/project_bootstrap.py"'
```

### Need more help?

See `PROJECT_BOOTSTRAP_GUIDE.md` for comprehensive reference.

---

## Real-World Lessons Built In

This bootstrap incorporates patterns from actual incidents solved in production projects:

### Example: Givebutter Playwright Visibility Pattern (2026-06-01)

**Problem:** 23 E2E tests timing out with "element is not visible" errors  
**Cause:** Tests clicking dynamic elements before they appeared in DOM  
**Fix:** Add visibility waits before interactive element clicks

**Code Pattern:**
```python
# ❌ WRONG - Times out if element not yet visible
button = await page.query_selector('button:has-text("Click Me")')
await button.click()  # 30-second timeout!

# ✅ RIGHT - Waits for element to appear first
await page.wait_for_selector('button:has-text("Click Me")', timeout=5000)
button = await page.query_selector('button:has-text("Click Me")')
await button.click()  # Complete in milliseconds
```

**Result:** 23 failing tests → all passing, 10-30x performance improvement

**Transferability:** This pattern applies to ANY browser automation + async backend combination

---

## The Philosophy

This bootstrap is built on lessons from real incidents (like the Givebutter E2E test failure). Every file serves a purpose:

- **CLAUDE.md** prevents mistakes (critical requirements enforced)
- **SKILL_*.md** transfers knowledge (best practices documented)
- **Pre-commit hook** automates enforcement (humans don't have to remember)
- **TESTING_GUIDE.md** establishes patterns (consistency from day 1)
- **CHECKLIST.md** ensures quality (verification before shipping)

**Result: Projects that are:**
- ✅ Safe (automation catches mistakes early)
- ✅ Consistent (everyone follows same patterns)
- ✅ Maintainable (clear guidelines)
- ✅ Fast to onboard (5 documents, 30 minutes, you understand everything)
- ✅ Learning-oriented (incidents documented, lessons transferred)

---

## Files in This Folder

| File | Purpose |
|------|---------|
| **project_bootstrap.py** | Main script - creates new projects |
| **BOOTSTRAP_README.md** | This file - quick start |
| **PROJECT_BOOTSTRAP_GUIDE.md** | Comprehensive reference |
| **Templates/** | TEMPLATE_*.md files for customization |
| **Memory/** | Learning system (how to learn from incidents) |

---

## Getting Started Right Now

```bash
# 1. Run the bootstrap
cd "/Users/gautambiswas/Claude Code"
python project_bootstrap.py

# 2. Answer the 4 prompts
# 3. Follow the output instructions
# 4. Start coding!
```

---

**Created:** 2026-06-01
**Status:** Ready to use
**Version:** 1.0
