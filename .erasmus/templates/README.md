# Erasmus XML Templates

This directory contains XML templates for the Erasmus context management system. These templates provide a structured format for organizing project information that can be used by AI models for better context understanding.

## Template Structure

- `meta_agent.xml`: Global rules that instruct the model on how to follow the workflow that allows it to use this context manager, this gets saved to the global rules file of your IDE.
- `meta_rules.xml`: The main template that includes placeholders for all other templates and gets saved to the local rules file of your project and updated from the `.ctx.` files.
- `architecture.xml`: Template for project architecture documentation, this gets copied to `.ctx.architecture.xml` and is monitored by `erasmus watch`
- `progress.xml`: Template for tracking project progress, this gets copied to `.ctx.progress.xml` and is monitored by `erasmus watch`
- `tasks.xml`: Template for managing current tasks and next steps, this gets copied to `.ctx.progress.xml` and is monitored by `erasmus watch`
- `protocol.xml`: Template for defining protocols, generic protocol template that will be used when creating a new template.
- `protocols/PROTOCOL.xml`: Predefined protocols for different aspects of code generation and library maintence. Use these to help augment the model and improve their targeted task.

## Template Format

Each template follows a consistent XML structure with:

- Clear hierarchical organization
- Descriptive element names
- Comments for guidance
- Placeholders for content

## Example Usage

```xml
<?xml version="1.0" encoding="UTF-8"?>
<MetaRules>
  <!--ARCHITECTURE-->
  <Architecture>
    <!-- Content from architecture.xml -->
  </Architecture>
  <!--/ARCHITECTURE-->

  <!--PROGRESS-->
  <Progress>
    <!-- Content from progress.xml -->
  </Progress>
  <!--/PROGRESS-->

  <!--TASKS-->
  <Tasks>
    <!-- Content from tasks.xml -->
  </Tasks>
  <!--/TASKS-->

  <!--PROTOCOL-->
  <Protocol>
    <!-- Content from protocol.xml -->
  </Protocol>
  <!--/PROTOCOL-->
</MetaRules>
```
