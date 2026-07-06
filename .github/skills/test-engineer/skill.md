# Test Engineering Skill

## Trigger
Always activate this skill when the user provides code that involves:
1.  A new Python Class or Function.
2.  An Agno Agent definition.
3.  A FastAPI endpoint.

## Deliverables
You must generate TWO separate test files for the code provided:

### 1. Unit Test (`tests/unit/test_filename.py`)
* **Library**: Use `pytest`.
* **Mocking**: specific strict rule: **Mock all external API calls** (OpenAI, Anthropic, Database).
* **Coverage**: Test success path, error handling, and edge cases (empty inputs).

### 2. Integration Test (`tests/integration/test_workflow.py`)
* **Definition of Done**: The feature is not "Done" until it runs end-to-end with a *real* or *local* emulator.
* **Structure**:
    1.  Setup: Initialize the Agno Agent.
    2.  Execution: Run the agent with a sample prompt.
    3.  Assertion: Verify the response has the expected structure (not exact text match, but JSON schema or key phrases).

## Example Output Format
```python
# tests/unit/test_agent.py
import pytest
from unittest.mock import MagicMock
from backend.agent import MyAgent

def test_agent_response():
    mock_llm = MagicMock()
    agent = MyAgent(model=mock_llm)