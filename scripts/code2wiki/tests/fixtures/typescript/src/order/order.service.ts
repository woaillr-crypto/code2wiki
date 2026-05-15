import { Injectable } from '@nestjs/common';
import { Order } from './order.entity';

@Injectable()
export class OrderService {
  async create(payload: any): Promise<Order> {
    // manager.transaction(async (tx) => { ... })
    return new Order();
  }

  async get(id: number): Promise<Order | null> {
    return null;
  }

  async updateStatus(id: number, status: string): Promise<void> {
    return;
  }
}
