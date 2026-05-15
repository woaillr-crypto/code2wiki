import { Entity, Column, PrimaryGeneratedColumn } from 'typeorm';

@Entity('t_order')
export class Order {
  @PrimaryGeneratedColumn()
  id: number;

  @Column()
  userId: number;

  @Column()
  amount: number;

  @Column()
  status: string;
}
