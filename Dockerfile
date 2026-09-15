FROM node:22-bookworm-slim AS node

FROM python:3.12-slim-bookworm AS build
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY backend/requirements.txt backend/requirements.txt
COPY scripts/run-app.mjs scripts/run-app.mjs
RUN node scripts/run-app.mjs setup
COPY . .
RUN npm run build

FROM python:3.12-slim-bookworm AS runtime
COPY --from=node /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY --from=build /app /app
ENV NODE_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 5173
CMD ["node", "scripts/run-app.mjs", "start"]
