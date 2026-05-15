import { Entity, Column, PrimaryGeneratedColumn } from 'typeorm';

@Entity('t_cart')
export class Cart {
  @PrimaryGeneratedColumn()
  id: number;

  @Column()
  userId: number;

  @Column()
  status: string;
}
