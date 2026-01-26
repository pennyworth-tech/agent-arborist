# Test Tasks: Echo Service

**Project**: Minimal echo test for devcontainer integration
**Total Tasks**: 2

## Task Specifications

### T001: Create echo script

Create a simple bash script that echoes a message.

**File**: `echo.sh`
```bash
#!/bin/bash
echo "Hello from devcontainer!"
```

Make it executable.

**Test**: Run `./echo.sh` and verify output contains "Hello from devcontainer!"

---

### T002: Create README

Create a README.md that documents the echo script.

**File**: `README.md`
```markdown
# Echo Script

Simple script that prints a greeting message.

## Usage
\```bash
./echo.sh
\```
```

**Test**: Verify README.md exists and contains usage instructions.

---

## Dependencies

```
T001 → T002
```
