---
name: Feature request
about: Suggest an idea for this project
title: ''
labels: enhancement

---

# What is needed?
A clear and concise description of what you want to happen.

# Background
More information about the feature needed

# Related issues
Paste here the related links for the issues on the clients/safe project if applicable. Please provide at least one of the following:
- Links to epics in your repository
- Images taken from mocks
- Gitbook or any form of written documentation links, etc. Any of these alternatives will help us contextualise your request.

# Endpoint
If applicable, description on the endpoint and the result you expect:

## URL
`GET /api/v1/safes/<address>/creation/`

## Response
```
{
  created: "<iso 8601 datetime>",
  transactionHash: "<keccak-hash>",
  creator: "<checksummed-address>"
}
```
