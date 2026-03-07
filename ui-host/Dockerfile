FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# Build both HTML entry points (host UI + sandbox proxy)
RUN INPUT=index.html npx vite build && INPUT=sandbox.html npx vite build

ENV HOST_PORT=8080
ENV SANDBOX_PORT=8081

EXPOSE 8080 8081

CMD ["npx", "tsx", "serve.ts"]
