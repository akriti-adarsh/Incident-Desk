FROM node:24-slim AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# The browser reaches the API on the host's published port in compose.
ARG VITE_API_BASE=http://localhost:8000
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
