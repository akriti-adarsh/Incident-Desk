# ADR-0001: Cross-tenant access answers 404, not 403

## Status
Accepted.

## Context
This is a multi-tenant system. A user in organisation A may try, by accident or
by probing, to read a resource belonging to organisation B by its direct id.

## Decision
Every org-scoped route resolves the organisation and the caller's membership in
a single query. If the caller is not a member of the organisation named in the
URL, the response is **404 Not Found**, identical to the response for an
organisation that does not exist. A 403 is reserved for the case where the
caller *is* in the organisation but their role does not permit the action.

## Consequences
- A 403 confirms a resource exists. Across a tenant boundary that is an
  information leak: org slugs and resource ids would become an oracle for
  enumerating another tenant's data. Answering 404 removes the oracle.
- The rule is enforced by a test parametrised over the live route table
  (`tests/test_tenant_isolation.py`): every org-scoped route is called by an
  owner of a *different* org and must return 404. Being an owner elsewhere
  guarantees the failure cannot be a role-based 403, so the 404 proves the
  boundary. New routes are covered automatically.
- The org scope is applied at the query level (a `WHERE org_id = ?` join),
  never by filtering results in Python after the fact, so there is no window
  where foreign rows are loaded.
