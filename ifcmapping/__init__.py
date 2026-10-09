"""IFCMapping: fill forms from building models with queries.

Layers (each depends only on the ones above it):

- ``mapping``     parameters and their queries, saved as JSON
- ``forms``       form adapters: read a template's parameters, write values into it
- ``extractors``  query languages: check, complete, evaluate, describe a source model
- ``assistant``   LLM chat that reads and proposes mappings through tools
- ``ui``          the NiceGUI app
"""
