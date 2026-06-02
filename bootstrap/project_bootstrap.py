#!/usr/bin/env python3
"""
Project Bootstrap Script

Creates a production-ready project structure with all necessary files for success:
- CLAUDE.md: Critical requirements, workflow, troubleshooting
- SKILL_*.md: Reusable knowledge for the domain
- Pre-commit hooks: Automated prevention mechanisms
- Testing guides: Test patterns and verification
- Configuration templates: .env, .gitignore, etc.

Usage:
    python project_bootstrap.py

Then follow the interactive prompts.
"""

import os
import sys
from pathlib import Path
from datetime import datetime


def prompt(message: str, default: str = "") -> str:
    """Prompt user for input with optional default."""
    if default:
        message = f"{message} [{default}]: "
    else:
        message = f"{message}: "

    result = input(message).strip()
    return result if result else default


def create_claude_md(project_name: str, domain: str) -> str:
    """Generate CLAUDE.md for the project."""
    return f"""# Project: {project_name}

## Quick Navigation

- [Critical Requirements](#critical-requirements) - Non-negotiables
- [Workflow](#workflow) - How to work on this project
- [Testing](#testing) - How to verify changes
- [Problem Solving](#problem-solving) - Troubleshooting guide
- [Key Documents](#key-documents) - Where to find details

---

## Critical Requirements

### Requirement 1: Code Quality

**NEVER do this:**
```python
# ❌ Commit code without testing
git commit -m "..."  # Without running tests first
```

**ALWAYS do this:**
```python
# ✅ Run tests before committing
pytest
git commit -m "..."
```

**Why it matters:**
- Prevents broken code from reaching main
- Catches regressions early
- Maintains team velocity

### Requirement 2: Documentation

**NEVER:**
- Add code without comments explaining the "why"
- Make architectural changes without updating CLAUDE.md
- Merge without updating relevant documentation

**ALWAYS:**
- Run `./scripts/verify.sh` before committing
- Update CLAUDE.md when adding new critical requirements
- Leave breadcrumbs for the next person

---

## Workflow

### Setup

```bash
# Clone and enter project
cd {project_name}

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Verify setup
pytest --collect-only
```

### Development

```bash
# Create feature branch
git checkout -b feature/your-feature-name

# Make changes following requirements above

# Test your changes
pytest

# Verify all checks pass
./scripts/verify.sh

# Commit (pre-commit hook will validate)
git commit -m "describe your change"
```

### Committing

```bash
# Pre-commit hook automatically:
# 1. Checks for code style issues
# 2. Blocks anti-patterns
# 3. Validates syntax
# 4. Prevents secrets from being committed

# If hook blocks your commit:
# 1. Read the error message
# 2. Check CLAUDE.md [Critical Requirements](#critical-requirements)
# 3. Fix the issue
# 4. Try committing again
```

---

## Testing

**Unit Tests:**
```bash
pytest tests/unit/
```

**Integration Tests:**
```bash
pytest tests/integration/
```

**Full Test Suite:**
```bash
pytest
```

**With Coverage:**
```bash
pytest --cov
```

---

## Problem Solving

### Issue: Pre-commit hook blocks my commit

**Solution:**
1. Read the error message carefully
2. Check [Critical Requirements](#critical-requirements) above
3. Reference [SKILL_{domain}.md](#key-documents) for best practices
4. Fix the issue
5. Commit again

### Issue: Tests are failing

**Solution:**
1. Run with verbose output: `pytest -v`
2. Check [TESTING_GUIDE.md](#key-documents)
3. Review [Incident History](#incident-history) for similar issues
4. Check if environment is set up correctly: `./scripts/verify.sh`

### Issue: I'm stuck

1. Check [Key Documents](#key-documents) below
2. Search this file (Ctrl+F)
3. Run diagnostic: `./scripts/diagnose.sh`
4. Ask someone who worked on this before

---

## Verification Checklist

Before committing, verify:

- [ ] Code follows style guidelines (linter passes)
- [ ] All tests pass: `pytest`
- [ ] No secrets in code: `grep -r "password\\|token\\|key" --exclude-dir=.git .`
- [ ] Documentation updated if behavior changed
- [ ] Pre-commit hook passes

---

## Key Documents

| Document | Purpose | When to Use |
|----------|---------|------------|
| SKILL_{domain}.md | Best practices for {domain} | Writing new code |
| TESTING_GUIDE.md | Testing patterns | Setting up tests |
| PREVENTION.md | Prevention mechanisms | Understanding automation |
| .github/CHECKLIST_{domain}.md | Pre-submission checklist | Before submitting PR |

---

## Architecture & Dependencies

### Key Components

```
{project_name}/
├── src/           - Production code
├── tests/         - Test suite
│   ├── unit/
│   └── integration/
├── scripts/       - Helper scripts
├── docs/          - Documentation
└── requirements.txt
```

### Required Environment

- Python 3.8+
- pytest (testing)
- [Add other critical dependencies]

---

## Pre-Commit Hook

This project uses a pre-commit hook to prevent common mistakes.

**Hook location:** `.git/hooks/pre-commit`

**What it checks:**
- [Add specific patterns you're blocking]
- Code style issues
- Syntax errors

**To bypass (only if absolutely necessary):**
```bash
git commit --no-verify
```

**Note:** Bypassing the hook should be rare. If you find yourself doing it often, the requirement might need adjustment.

---

## Git Workflow

```bash
# Always work on a feature branch
git checkout -b feature/descriptive-name

# Commit frequently with clear messages
git commit -m "what you changed and why"

# Push to remote when ready for review
git push -u origin feature/descriptive-name

# Create PR and wait for review
# Don't merge your own PRs
```

---

## Incident History

Recent issues and what we learned:

- None yet (this is a new project!)

When incidents happen, document them in your memory system.

---

## Maintenance

### Regular Tasks

- [ ] Review test coverage monthly
- [ ] Update dependencies quarterly
- [ ] Check for security issues: `pip audit`
- [ ] Review and update CLAUDE.md if requirements changed

---

**Last Updated:** {date}
**Status:** Active
**Maintained By:** [Your Name]
"""


def create_skill_md(project_name: str, domain: str) -> str:
    """Generate SKILL_*.md for the project domain."""
    return f"""# SKILL: Best Practices for {domain}

**Domain:** {domain}
**Project:** {project_name}
**Purpose:** Document the "right way" to work in this domain

---

## Overview

This skill captures best practices, patterns, and anti-patterns specific to {domain} development.

### Use this skill when:
- Writing new code in {domain}
- Reviewing code from teammates
- Debugging issues in {domain}
- Onboarding to this project

**Time to read:** 20 minutes
**Skill level required:** Intermediate

---

## Core Concepts

### Concept 1: [Key Pattern in Your Domain]

**Definition:** [Explain what this means]

**Example - Wrong:**
```python
# ❌ Anti-pattern
# [example of wrong way]
```

**Example - Right:**
```python
# ✅ Best practice
# [example of right way]
```

**Why it matters:**
- [Consequence if done wrong]
- [Benefit of doing it right]

---

## Common Patterns

### Pattern 1: [Describe a successful approach in your domain]

**When to use:** [Scenario where this applies]

**Implementation:**
```python
# [Working code example]
```

**Pros:**
- [Advantage 1]
- [Advantage 2]

**Cons:**
- [Disadvantage 1]

---

## Anti-Patterns to Avoid

| Anti-Pattern | Why It's Bad | What To Do Instead |
|--------------|-------------|-------------------|
| [Common mistake 1] | [Impact] | [Better approach] |
| [Common mistake 2] | [Impact] | [Better approach] |

---

## Testing Strategy

### Unit Tests

```python
def test_your_feature():
    # Setup
    # Execute
    # Verify
    pass
```

### Integration Tests

- [How to test across components]

---

## Troubleshooting

### Problem: [Common issue in your domain]

**Symptoms:** [What you observe]

**Root cause:** [Why it happens]

**Solution:**
```python
# [How to fix]
```

**Prevention:**
- [How to avoid in future]

---

## Related Skills

- CLAUDE.md (project guidelines)
- TESTING_GUIDE.md (testing patterns)

---

**Version:** 1.0
**Created:** {date}
**Status:** Active
**Domain:** {domain}
"""


def create_testing_guide() -> str:
    """Generate TESTING_GUIDE.md."""
    return """# Testing Guide

## Test Organization

```
tests/
├── unit/           - Fast, isolated tests
├── integration/    - Tests across components
└── conftest.py     - Shared fixtures
```

## Running Tests

```bash
# All tests
pytest

# Specific file
pytest tests/unit/test_feature.py

# Specific test
pytest tests/unit/test_feature.py::test_function_name

# With coverage
pytest --cov

# Verbose output
pytest -v

# Stop on first failure
pytest -x

# Show print statements
pytest -s
```

## Writing Tests

### Unit Test Template

```python
def test_function_does_something():
    \"\"\"Test that function returns expected value.\"\"\"
    # Arrange
    input_data = ...
    expected = ...

    # Act
    result = function(input_data)

    # Assert
    assert result == expected
```

### Integration Test Template

```python
def test_components_work_together(client):
    \"\"\"Test that components integrate correctly.\"\"\"
    # Setup
    # Call multiple components
    # Verify behavior across them
    pass
```

## Test Naming

- Start with `test_`
- Describe what is being tested
- Describe the scenario and expected outcome
- Example: `test_login_with_valid_credentials_succeeds`

## Best Practices

1. **One assertion per test** (or related assertions)
2. **Clear test names** (should describe what they test)
3. **Use fixtures** (don't repeat setup code)
4. **Mock external dependencies** (keep tests fast)
5. **Test behavior, not implementation** (make refactoring easier)

## Common Issues

### Test is flaky (sometimes passes, sometimes fails)

- **Cause:** Usually timing issues, randomness, or test order dependencies
- **Solution:** Add explicit waits, seed random generators, use `pytest --random-order-seed=0`

### Test is slow

- **Cause:** I/O, external calls, heavy computation
- **Solution:** Mock external calls, use fixtures, parallelize with `pytest-xdist`

### Test won't run

- **Cause:** Import error, missing dependency, syntax error
- **Solution:** Run `pytest --collect-only` to see what's discoverable

---

**Always run tests before committing!**
"""


def create_prevention_md(domain: str) -> str:
    """Generate PREVENTION.md."""
    return f"""# Prevention Mechanisms for {domain}

This project uses automated prevention to catch common mistakes before they reach production.

## What Gets Blocked

### Pre-commit Hook

The `.git/hooks/pre-commit` hook runs before every commit and blocks:

- [Anti-pattern 1 in your domain]
- [Anti-pattern 2]
- Hardcoded secrets (passwords, API keys)
- Large files (> 10MB)
- Syntax errors

### Why Prevention Matters

Without prevention:
- Mistakes reach production
- Developers have to remember rules
- Same issues recur across projects

With prevention:
- Humans never commit anti-patterns
- Rules are enforced automatically
- Issues are caught at the earliest point

## Installing the Hook

The hook is automatically installed when you run setup. To verify:

```bash
ls -la .git/hooks/pre-commit
```

## If the Hook Blocks Your Commit

1. **Read the error message** - it tells you what's wrong
2. **Check CLAUDE.md** - review the Critical Requirements section
3. **Fix the issue** - make the change
4. **Try again** - `git commit -m "..."`

Only bypass if absolutely necessary:
```bash
git commit --no-verify  # Only in emergencies!
```

## Monitoring

To see if prevention mechanisms are working:

```bash
# Check if hook blocks an anti-pattern
git diff --cached | grep "[pattern]"

# Check recent commits for violations
git log --all --oneline | grep -i revert
```

---

**Prevention is better than detection. Prevention is better than fixes. Prevention is best.**
"""


def create_checklist_md(domain: str) -> str:
    """Generate .github/CHECKLIST_*.md."""
    return f"""# Pre-Submission Checklist for {domain}

Use this before committing or submitting a PR.

## Code Quality

- [ ] Code follows project style (no linter errors)
- [ ] All tests pass: `pytest`
- [ ] No hardcoded secrets (passwords, tokens, keys)
- [ ] No debug code or print statements
- [ ] Variable names are clear and descriptive

## Testing

- [ ] New code has tests
- [ ] All existing tests still pass
- [ ] Test names clearly describe what they test
- [ ] Tests cover happy path and error cases
- [ ] No flaky tests (run twice to verify)

## Documentation

- [ ] Code comments explain the "why" not the "what"
- [ ] Function docstrings are present and clear
- [ ] CLAUDE.md updated if behavior changed
- [ ] README or relevant docs updated
- [ ] Complex logic has inline comments

## Pre-Commit Checks

- [ ] Pre-commit hook passes (no blocking errors)
- [ ] Git history is clean (meaningful commit messages)
- [ ] No merged branches left in history

## Final Review

- [ ] I've tested this locally
- [ ] I've read CLAUDE.md critical requirements
- [ ] I've checked SKILL_{domain}.md for patterns
- [ ] I've reviewed similar code for consistency
- [ ] I'm confident this is production-ready

---

If any item fails:
1. Fix it
2. Run tests again
3. Come back to this checklist
4. Verify all items before committing

**Don't commit if any item is unchecked!**
"""


def create_gitignore() -> str:
    """Generate .gitignore."""
    return """# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg
venv/
ENV/
env/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Testing
.pytest_cache/
.coverage
htmlcov/
.tox/

# Secrets & Config
.env
.env.local
.env.*.local
secrets.json
credentials.json
token.json

# Project specific
*.db
*.sqlite
*.sqlite3
.run_log

# OS
Thumbs.db
.DS_Store

# Temp files
*.tmp
*.temp
*.bak
"""


def create_env_example() -> str:
    """Generate .env.example."""
    return """# Environment Configuration Template
# Copy to .env and fill in your values

# Application
DEBUG=False
APP_NAME=your-app-name

# Database (if applicable)
DATABASE_URL=sqlite:///app.db

# API Keys (if applicable)
API_KEY=your-api-key-here

# Logging
LOG_LEVEL=INFO

# Other
# Add other environment variables here
"""


def create_precommit_hook(domain: str) -> str:
    """Generate pre-commit hook script."""
    return f"""#!/bin/bash
# Pre-commit hook for {domain} projects
# Purpose: Block common mistakes before they reach git history

set -e

# Check for secrets
if git diff --cached | grep -E "password|api_key|secret|token|credentials" | grep -v ".example" > /dev/null; then
    echo "❌ Error: Potential secrets detected in staged changes"
    echo "   Do not commit passwords, API keys, or credentials"
    echo "   Use .env and .env.example instead"
    exit 1
fi

# Check for large files
LARGE_LIMIT=10485760  # 10MB
while IFS= read -r file; do
    if [ -f "$file" ]; then
        size=$(stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null)
        if [ $size -gt $LARGE_LIMIT ]; then
            echo "❌ Error: File too large: $file ($((size / 1048576))MB)"
            echo "   Limit is 10MB. Use git-lfs or exclude from git."
            exit 1
        fi
    fi
done < <(git diff --cached --name-only)

# Check for Python syntax errors
if git diff --cached --name-only | grep -E "\\.py$" > /dev/null; then
    echo "Checking Python syntax..."
    python -m py_compile $(git diff --cached --name-only | grep -E "\\.py$") || {{
        echo "❌ Syntax error in Python files"
        exit 1
    }}
fi

echo "✅ Pre-commit checks passed"
exit 0
"""


def create_readme(project_name: str, domain: str, description: str) -> str:
    """Generate README.md."""
    return f"""# {project_name}

{description}

## Quick Start

### Prerequisites

- Python 3.8+
- pip or poetry

### Setup

```bash
# Clone repository
git clone <repository-url>
cd {project_name}

# Create virtual environment
python -m venv venv
source venv/bin/activate  # or: .\\venv\\Scripts\\activate on Windows

# Install dependencies
pip install -r requirements.txt

# Run tests to verify setup
pytest
```

## Development

See [CLAUDE.md](CLAUDE.md) for:
- Critical requirements
- Development workflow
- How to contribute
- Troubleshooting guide

See [SKILL_{domain}.md](SKILL_{domain}.md) for:
- Best practices for {domain}
- Common patterns
- Anti-patterns to avoid

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov

# Run specific test file
pytest tests/unit/test_feature.py
```

For more details, see [TESTING_GUIDE.md](TESTING_GUIDE.md).

## Project Structure

```
{project_name}/
├── src/              - Production code
├── tests/            - Test suite
│   ├── unit/
│   └── integration/
├── scripts/          - Helper scripts
├── docs/             - Documentation
├── CLAUDE.md         - Project guidelines (READ THIS FIRST)
├── SKILL_{domain}.md - Best practices for {domain}
├── TESTING_GUIDE.md  - How to write tests
├── README.md         - This file
└── requirements.txt  - Python dependencies
```

## Key Documentation

| Document | Purpose |
|----------|---------|
| [CLAUDE.md](CLAUDE.md) | Critical requirements, workflow, troubleshooting |
| [SKILL_{domain}.md](SKILL_{domain}.md) | Best practices for {domain} |
| [TESTING_GUIDE.md](TESTING_GUIDE.md) | How to write and run tests |
| [.github/CHECKLIST_{domain}.md](.github/CHECKLIST_{domain}.md) | Pre-submission checklist |

## Contributing

1. Read [CLAUDE.md](CLAUDE.md)
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Make changes following [SKILL_{domain}.md](SKILL_{domain}.md)
4. Write tests for new code
5. Run `pytest` to verify everything passes
6. Use the [.github/CHECKLIST_{domain}.md](.github/CHECKLIST_{domain}.md) before committing
7. Commit with clear messages: `git commit -m "describe what you changed"`
8. Push: `git push origin feature/your-feature`

## Support

- Check [CLAUDE.md](CLAUDE.md) for common issues and solutions
- Read [SKILL_{domain}.md](SKILL_{domain}.md) for best practices
- Review [TESTING_GUIDE.md](TESTING_GUIDE.md) for testing questions

---

**Created:** {datetime.now().strftime('%Y-%m-%d')}
"""


def create_requirements_txt() -> str:
    """Generate requirements.txt."""
    return """# Core dependencies
pytest>=7.0.0
pytest-cov>=3.0.0

# Add project-specific dependencies below
# Example:
# requests>=2.28.0
# pydantic>=1.9.0
"""


def main():
    """Main script execution."""
    print("\n" + "=" * 60)
    print("Project Bootstrap - Create Production-Ready Projects")
    print("=" * 60 + "\n")

    # Get project path
    project_path = prompt(
        "Project path (absolute or relative)",
        default="./my-new-project"
    )

    # Resolve path
    project_dir = Path(project_path).expanduser().resolve()

    # Get project metadata
    print("\n" + "-" * 60)
    print("Project Metadata")
    print("-" * 60 + "\n")

    project_name = prompt(
        "Project name",
        default=project_dir.name
    )

    domain = prompt(
        "Technology/Domain (e.g., 'Python Web API', 'Browser Automation', 'Data Pipeline')",
        default="Python"
    )

    description = prompt(
        "Brief description",
        default="A new project"
    )

    # Confirm
    print("\n" + "-" * 60)
    print("Summary")
    print("-" * 60)
    print(f"Project Name:  {project_name}")
    print(f"Project Path:  {project_dir}")
    print(f"Domain:        {domain}")
    print(f"Description:   {description}")
    print("-" * 60 + "\n")

    confirm = prompt("Create project? (y/n)", default="y")
    if confirm.lower() != "y":
        print("Cancelled.")
        sys.exit(0)

    # Create directory structure
    print("\n📁 Creating directory structure...")
    project_dir.mkdir(parents=True, exist_ok=True)

    (project_dir / ".github").mkdir(exist_ok=True)
    (project_dir / "scripts").mkdir(exist_ok=True)
    (project_dir / "src").mkdir(exist_ok=True)
    (project_dir / "tests" / "unit").mkdir(parents=True, exist_ok=True)
    (project_dir / "tests" / "integration").mkdir(parents=True, exist_ok=True)
    (project_dir / "docs").mkdir(exist_ok=True)

    current_date = datetime.now().strftime("%Y-%m-%d")

    # Create files
    files_to_create = {
        "CLAUDE.md": create_claude_md(project_name, domain),
        f"SKILL_{domain.upper().replace(' ', '_')}.md": create_skill_md(project_name, domain),
        "TESTING_GUIDE.md": create_testing_guide(),
        "PREVENTION.md": create_prevention_md(domain),
        ".github/CHECKLIST.md": create_checklist_md(domain),
        ".gitignore": create_gitignore(),
        ".env.example": create_env_example(),
        "README.md": create_readme(project_name, domain, description),
        "requirements.txt": create_requirements_txt(),
        "tests/conftest.py": "# Shared test fixtures go here\n",
        "src/__init__.py": '"""Main package."""\n',
        "docs/README.md": f"# {project_name} Documentation\n\nAdd documentation here.\n",
    }

    print("\n📝 Creating files...")
    for filename, content in files_to_create.items():
        filepath = project_dir / filename
        filepath.write_text(content)
        print(f"   ✓ {filename}")

    # Create pre-commit hook
    print("\n🔧 Setting up git hooks...")
    git_dir = project_dir / ".git"
    hooks_dir = git_dir / "hooks"

    # Initialize git if not already
    if not git_dir.exists():
        os.system(f"cd '{project_dir}' && git init")

    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_file = hooks_dir / "pre-commit"
    hook_file.write_text(create_precommit_hook(domain))
    hook_file.chmod(0o755)
    print(f"   ✓ Pre-commit hook installed")

    # Create initial commit
    print("\n📦 Creating initial commit...")
    os.system(f"cd '{project_dir}' && git add . && git commit -m 'chore: Project bootstrap with templates and guidelines'")

    print("\n" + "=" * 60)
    print("✅ Project Created Successfully!")
    print("=" * 60)
    print(f"\n📂 Location: {project_dir}")
    print("\n📖 Next Steps:")
    print(f"   1. cd {project_dir}")
    print("   2. Read CLAUDE.md (critical requirements)")
    print(f"   3. Read SKILL_*.md (best practices for {domain})")
    print("   4. Create virtual environment: python -m venv venv")
    print("   5. Activate: source venv/bin/activate")
    print("   6. Install: pip install -r requirements.txt")
    print("   7. Start coding!")
    print("\n💡 Key Documents:")
    print("   • CLAUDE.md - Project guidelines and workflow")
    print("   • SKILL_*.md - Best practices for your domain")
    print("   • TESTING_GUIDE.md - How to write tests")
    print("   • .github/CHECKLIST.md - Pre-submission checklist")
    print("\n" + "=" * 60 + "\n")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nCancelled by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)
