# Project Bootstrap Guide

## Overview

The `project_bootstrap.py` script creates production-ready projects with all necessary files for success. It's based on the learning capture system developed from the Givebutter E2E test incident.

## Quick Start

```bash
cd "/Users/gautambiswas/Claude Code"
python project_bootstrap.py

# Then follow the interactive prompts:
# 1. Enter project path
# 2. Confirm project name
# 3. Specify technology/domain
# 4. Brief description
# 5. Confirm creation
```

## What Files Get Created

### Core Project Files

1. **CLAUDE.md** (Critical)
   - Project guidelines and critical requirements
   - Development workflow (setup, development, testing, committing)
   - Common issues and solutions
   - References to other key documents
   - **Use when:** Starting work, debugging, or onboarding

2. **SKILL_[DOMAIN].md** (Critical)
   - Best practices for your technology domain
   - Common patterns and anti-patterns
   - Code examples (right vs wrong ways)
   - Testing strategy specific to domain
   - Troubleshooting guide
   - **Use when:** Writing code, reviewing code, solving domain-specific problems

3. **TESTING_GUIDE.md**
   - Test organization and structure
   - How to run tests
   - Test naming conventions
   - Test templates (unit, integration)
   - Common test issues and fixes
   - **Use when:** Writing tests or debugging test failures

4. **PREVENTION.md**
   - Overview of what's automatically blocked
   - Explanation of why prevention mechanisms matter
   - How to work with pre-commit hooks
   - Monitoring prevention effectiveness
   - **Use when:** Understanding automation or debugging hook issues

### Configuration & Setup

5. **.env.example**
   - Template for environment variables
   - Copy to `.env` and fill in your values
   - **Never commit `.env`** (it's in `.gitignore`)

6. **.gitignore**
   - Python (venv, __pycache__, .eggs)
   - IDE (.vscode, .idea)
   - Testing (.pytest_cache, coverage)
   - Secrets (.env, credentials)
   - Project-specific (*.db, .run_log)

7. **requirements.txt**
   - Core dependencies (pytest, pytest-cov)
   - Placeholder for project-specific packages
   - **Use:** `pip install -r requirements.txt`

### Documentation

8. **README.md**
   - Project overview
   - Quick start guide
   - Project structure
   - Development workflow
   - Links to key documents
   - **Use when:** First-time setup or onboarding

9. **.github/CHECKLIST.md**
   - Pre-submission checklist
   - Code quality, testing, documentation checks
   - Final review before committing
   - **Use before:** Every commit

10. **docs/README.md**
    - Placeholder for project documentation
    - Add architecture docs, design guides, etc.

### Directory Structure

11. **Source Code**
    ```
    src/
    └── __init__.py
    ```

12. **Tests**
    ```
    tests/
    ├── conftest.py      (shared fixtures)
    ├── unit/            (fast, isolated tests)
    └── integration/     (tests across components)
    ```

13. **Scripts**
    ```
    scripts/             (helper scripts)
    ```

14. **Git Hooks**
    ```
    .git/hooks/pre-commit
    ```
    - Blocks hardcoded secrets
    - Blocks large files (>10MB)
    - Checks Python syntax
    - Customizable for project-specific patterns

## What Makes This Bootstrap Different

### Traditional Setup
1. Create folder
2. Copy some files manually
3. Write CLAUDE.md from scratch
4. Hope you don't forget something

**Result:** Inconsistent projects, missing critical files, repeated work

### With Bootstrap
1. Run script
2. Answer 4 questions
3. Get complete, customized project
4. All critical files in place
5. Git configured with safety hooks
6. Ready to code in 2 minutes

**Result:** Consistent projects, no missing pieces, faster onboarding

## File Relationships

```
CLAUDE.md (read first)
  ├─→ SKILL_[DOMAIN].md (best practices)
  ├─→ TESTING_GUIDE.md (how to test)
  ├─→ .github/CHECKLIST.md (before committing)
  └─→ PREVENTION.md (automation)

README.md (project overview)
  └─→ links to all of above

.git/hooks/pre-commit (automated enforcement)
  └─→ enforces rules from CLAUDE.md
```

## Customization

After bootstrap, customize these files for your project:

### 1. Update CLAUDE.md

```markdown
## Critical Requirements

### Requirement 1: [Your first rule]

**NEVER:**
```
[your anti-pattern]
```

**ALWAYS:**
```
[your pattern]
```
```

### 2. Enhance SKILL_[DOMAIN].md

Add patterns specific to your project:
- Real code examples from your codebase
- Domain-specific best practices
- Your project's patterns

### 3. Update Pre-commit Hook

In `.git/hooks/pre-commit`, add project-specific pattern blocking:

```bash
# Block your specific anti-patterns
if git diff --cached | grep -q "your_anti_pattern"; then
    echo "❌ Error: Anti-pattern detected"
    exit 1
fi
```

### 4. Fill in .env.example

List all environment variables your project needs:

```bash
# .env.example
DATABASE_URL=postgres://localhost/mydb
API_KEY=your-api-key-here
DEBUG=False
```

## Recommended Reading Order

When you first run the bootstrap:

1. **README.md** (2 min) - Quick overview
2. **CLAUDE.md** (5 min) - Critical requirements and workflow
3. **SKILL_[DOMAIN].md** (15 min) - Best practices for your tech
4. **TESTING_GUIDE.md** (5 min) - How to write tests
5. **.github/CHECKLIST.md** (3 min) - Before your first commit

**Total:** 30 minutes to understand everything

## Using Bootstrap in Multiple Projects

### Scenario 1: Different Domains

```bash
# Python Web API
python project_bootstrap.py
# → Creates project with Python best practices

# React Frontend (in different session)
python project_bootstrap.py
# → Creates project with JavaScript/React best practices
```

### Scenario 2: Similar Projects

```bash
# First project
python project_bootstrap.py
# → Creates project-1/

# Second similar project
python project_bootstrap.py
# → Creates project-2/
# → Same structure, can copy SKILL_*.md between them
```

## Troubleshooting

### The script won't run

```bash
# Make sure it's executable
chmod +x "/Users/gautambiswas/Claude Code/project_bootstrap.py"

# Run with python explicitly
python "/Users/gautambiswas/Claude Code/project_bootstrap.py"
```

### Files weren't created

```bash
# Check if project directory was created
ls -la /path/to/project/

# Verify git was initialized
cd /path/to/project
git log --oneline
```

### Pre-commit hook not working

```bash
# Verify hook is executable
ls -la .git/hooks/pre-commit

# Make executable if needed
chmod +x .git/hooks/pre-commit

# Test hook manually
.git/hooks/pre-commit
```

## What Makes a Project Successful

Based on the Givebutter E2E test incident and the learning capture system, a successful project has:

✅ **CLAUDE.md** - Clear guidelines everyone understands
✅ **SKILL_*.md** - Best practices for the domain
✅ **Tests** - Comprehensive test suite with clear patterns
✅ **Pre-commit hooks** - Automated prevention of common mistakes
✅ **Documentation** - Clear workflow and troubleshooting guide
✅ **Checklists** - Verification steps before committing
✅ **Git discipline** - Clean history with clear commit messages

This bootstrap includes all of them.

## Beyond Bootstrap

After bootstrap creates the initial structure, projects grow through:

1. **Incident Documentation** (when things go wrong)
   - Use TEMPLATE_incident_learning_capture.md
   - Update CLAUDE.md with lessons learned
   - Add prevention mechanisms to pre-commit hook

2. **Skill Enhancement** (as patterns emerge)
   - Update SKILL_[DOMAIN].md with new patterns
   - Add anti-patterns as they're discovered
   - Include real examples from your codebase

3. **Automation Expansion** (as incidents recur)
   - Add linter rules
   - Expand pre-commit hook
   - Add CI/CD checks

4. **Knowledge Transfer** (for new team members)
   - They read CLAUDE.md first
   - They read SKILL_*.md
   - They run through CHECKLIST.md
   - They understand "why" behind everything

## Integration with Memory System

This bootstrap connects to your memory system:

```
project_bootstrap.py creates →  CLAUDE.md, SKILL_*.md
                                    ↓
                         Used in projects
                                    ↓
                         When incidents happen →  Documented in memory
                                    ↓
                         Lessons feed back into templates
```

The templates in your memory system:
- TEMPLATE_incident_learning_capture.md
- TEMPLATE_reusable_skill.md
- TEMPLATE_project_claude_md.md
- TEMPLATE_automation_prevention.md

Are the sources that inform what `project_bootstrap.py` creates.

---

**Created:** 2026-06-01
**Version:** 1.0
**Status:** Active
