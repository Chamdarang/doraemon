FROM node:22-bookworm-slim

WORKDIR /app

COPY package.json package-lock.json ./

RUN npm ci

COPY . .

ARG NEXT_PUBLIC_POCKET_API_URL=http://localhost:8000/api
ENV NEXT_PUBLIC_POCKET_API_URL=${NEXT_PUBLIC_POCKET_API_URL}

RUN npm run build

ENV HOST=0.0.0.0
ENV PORT=3000

EXPOSE 3000

CMD ["npm", "run", "start"]