import { Processor, Process } from '@nestjs/bullmq';
import { Job } from 'bullmq';

@Processor('cart-events')
export class CartProcessor {
  @Process('cart.checkout')
  async onCheckout(job: Job): Promise<void> {
    // handle checkout
  }
}
