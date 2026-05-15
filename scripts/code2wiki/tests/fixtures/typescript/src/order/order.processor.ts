import { Processor, Process } from '@nestjs/bullmq';
import { Job } from 'bullmq';

@Processor('order-events')
export class OrderProcessor {
  @Process('order.created')
  async onOrderCreated(job: Job): Promise<void> {
    // handle order created
  }

  @Process('order.payment.retry')
  async onRetryPayment(job: Job): Promise<void> {
    // retry
  }
}
