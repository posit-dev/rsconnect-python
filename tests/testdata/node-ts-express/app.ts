import express, { type Request, type Response } from 'express';

const app = express();
const PORT = process.env.PORT || 3000;

app.get('/', (req: Request, res: Response) => {
    res.json({ status: 'ok', framework: 'express', language: 'typescript' });
});

app.get('/health', (req: Request, res: Response) => {
    res.status(200).send('OK');
});

app.listen(PORT, () => {
    console.log(`TypeScript Express server listening on port ${PORT}`);
});
