# Migration Assessment

This document summarizes the migration options discussed for moving Baby Buddy toward a React frontend and/or a Java Spring Boot backend.

## Current Architecture

Baby Buddy is currently a Django application with server-rendered templates, Django models, Django authentication, Django permissions, and a Django REST Framework API.

The existing frontend is not React. It is mostly Django templates with Bootstrap, jQuery, Plotly, SCSS, and a Gulp-based asset pipeline.

The existing REST API is a strong starting point for a React migration because it already exposes the main domain objects such as children, feedings, sleep, diaper changes, timers, tags, measurements, and profile data.

## React Frontend Migration

A React migration is feasible and should be done incrementally.

React should replace the Django template UI screen by screen while Django continues to own the backend, database, authentication, permissions, and API.

Good first migration targets:

- Custom `last-feeding` page
- Dashboard
- Timers
- Quick-entry forms for feeding, sleep, diaper changes, and measurements

Harder migration targets:

- Timeline, because it currently aggregates multiple models server-side
- Reports, because Python currently generates Plotly HTML and JavaScript
- Django forms, because they contain defaulting behavior such as selecting the only child, deriving values from timers, copying the last feeding method, and setting nap defaults

Recommended additions before a large React migration:

- A frontend bootstrap endpoint for current user, settings, permissions, timezone, and base paths
- A clear CSRF strategy for React requests
- JSON endpoints for dashboard summaries, timeline events, quick timer actions, and report data
- API support for form choices and default values
- A React build path, likely using Vite, that can coexist with or replace the current Gulp pipeline

## Django To Spring Boot Migration

Moving from Django to Spring Boot is possible, but it is a backend rewrite rather than a direct language conversion.

The Django backend would need to be reimplemented in Java:

- Django models to JPA/Hibernate entities
- Django ORM queries to repositories and services
- Django REST Framework viewsets to Spring REST controllers
- Django permissions and auth to Spring Security
- Django migrations to Flyway or Liquibase
- Python report and timeline logic to Java services or JSON endpoints
- Django templates to React, Thymeleaf, or another frontend approach

This migration is larger and riskier than moving the frontend to React because it replaces the core backend behavior.

## Estimated Timelines

For one experienced developer, rough estimates are:

### React Frontend Migration

- Small pilot page such as `last-feeding`: 1-3 days
- React setup plus auth/API plumbing: 3-5 days
- Dashboard, timers, and quick-entry forms: 1-3 weeks
- Most CRUD screens: 4-8 weeks
- Full UI including reports, timeline, settings, and polish: 8-14 weeks

### Spring Boot Backend Migration

- Basic Spring Boot API scaffold: 1-2 weeks
- CRUD APIs, entities, and security: 6-10 weeks
- Timeline, reports, tags, uploads, permissions, and settings: 8-16 additional weeks
- Full production replacement with migration and testing: 3-6 months

### Doing Both

If the final goal is React plus Spring Boot, the safest order is:

1. Keep Django running.
2. Build React against the existing Django API.
3. Freeze the API contract.
4. Build Spring Boot to match that contract.
5. Switch React from the Django API to the Spring API when Spring matches the required behavior.

A careful full migration to React plus Spring Boot would likely take 4-8 months.

## Repository Layout

The migrations do not have to be split into separate repositories.

For migration work, a monorepo is usually easier because frontend, backend, API contracts, tests, and deployment changes can evolve together.

Possible monorepo layout:

```text
/opt/babybuddy
  /backend-django
  /backend-spring
  /frontend-react
```

Less disruptive starting layout:

```text
/opt/babybuddy
  /react-app
  existing Django files
```

Separate repositories may make sense later if the frontend and backend will have separate teams, separate deployments, or separate release cadences. During migration, keeping everything together is usually simpler.

## Recommendation

Start with the React migration while keeping Django as the backend. This creates a cleaner API-driven frontend and makes any future Spring Boot rewrite easier to validate.

Avoid rewriting the frontend and backend at the same time unless there is a strong operational reason to do so. Migrating one layer at a time reduces risk and makes testing much easier.
