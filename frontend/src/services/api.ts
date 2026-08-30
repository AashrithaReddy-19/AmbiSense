import axios from 'axios';
export const api = axios.create({baseURL: import.meta.env.VITE_API_URL || '/api', timeout: 30000});
api.interceptors.request.use(config=>{const token=localStorage.getItem('ambisense_token');if(token)config.headers.Authorization=`Bearer ${token}`;return config});
api.interceptors.response.use(response=>response,error=>{if(error.response?.status===401){localStorage.removeItem('ambisense_token');window.dispatchEvent(new Event('ambisense-auth-expired'))}return Promise.reject(error)});
