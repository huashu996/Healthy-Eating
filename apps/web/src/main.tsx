import React from 'react';
import { createRoot } from 'react-dom/client';
import { App } from './App';
import './styles.css';
import './simple.css';
import './diet-mobile.css';
import './diet-apple.css';
createRoot(document.getElementById('root')!).render(<React.StrictMode><App/></React.StrictMode>);
