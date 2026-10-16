FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev || npm install --omit=dev
COPY index.mjs ./
USER node
CMD ["node", "index.mjs"]
